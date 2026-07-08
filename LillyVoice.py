"""LillyVoice — Matrix voice-memo bot, part of the LillyAI stack.

Runs on the lilly host. Syncs as YOUR account (@chloe) using a dedicated
access token, so it sees every room you are already in — including the
WhatsApp/Signal/Telegram bridge portals — WITHOUT joining anything itself.
Whenever a voice memo (an `m.audio` event) appears in a chlo.ee-hosted room —
whether you received it OR sent it yourself — it downloads the audio, splits it
into <=28 s chunks (Gemma 4's audio
input is capped at 30 s per request), asks the llama.cpp server on the `ai` host
to transcribe each chunk, then to summarise the joined transcript, and posts the
summary back into the SAME room as a labelled reply to the memo.

Optionally, drafts + status notices in the drafts room can instead be posted by
Lilly's own Matrix account (@lilly) via a second, send-only client — see
MATRIX_LILLY_USER_ID / MATRIX_LILLY_TOKEN below. When both are set, the primary
account (@chloe) still does the sync, the memo summaries and any approved sends
into the bridged portals; only the drafts-room posts (drafts + notices) move to
Lilly's account. When unset, everything (including drafts) stays on the primary
account, exactly as before.

Posting as you, into the chat
-----------------------------
The reply is sent as @chloe (the account we sync as), which is the bridges'
puppet, so mautrix relays it OUT to the WhatsApp/Signal/Telegram conversation —
the summary lands in the real chat, visible to the other participant(s), and on
their side appears as a message from you. That's intentional: a separate bot
account can't sit in WhatsApp/Telegram portals (WhatsApp 403s a foreign member,
mautrix-telegram kicks unpermitted users), so the puppet is the only sender that
reaches every messenger. Because of that, every summary is clearly prefixed with
a bot marker (BOT_PREFIX) that survives all three bridges (a leading emoji +
plain-text label — rich formatting is mangled differently per messenger).

Notes
-----
* AUTH is a pre-minted access token for @chloe (sops matrix/voicebot-env). Mint a
  DEDICATED device for it (initial_device_display_name=voicebot) so logging your
  normal clients out doesn't kill the bot, and vice-versa.
* Every voice memo in the room is summarised — both those you receive AND ones
  you send yourself. The reply is an m.text (not m.notice — bridges relay m.text;
  m.notice is often dropped).
* Only chlo.ee-hosted rooms (room id !…:chlo.ee) are considered.
* BACKLOG is skipped: one throwaway sync advances next_batch before any handler
  runs, so a restart never re-summarises old memos.
* E2EE rooms ARE supported (olm crypto store under STATE_DIR): the bot decrypts
  incoming memos and encrypts its reply. Caveats — only messages sent after the
  bot's device exists decrypt (no history), and for reliable key-sharing you may
  need to verify the bot's device. Verifying: just click "Verify" on the
  `voicebot` session in Element and tap "They match" — the bot answers the
  request/ready/start flow and auto-confirms the emoji (no comparison — your own
  device, own server). Do NOT start a second verification at the same time
  (e.g. a bot-initiated one): two concurrent SAS for the same device collide and
  Element aborts both. Bridge portals are plaintext (bridge encryption off).

Environment (EnvironmentFile = sops matrix/voicebot-env):
    MATRIX_HOMESERVER     e.g. http://localhost:8008   (synapse, loopback)
    MATRIX_USER_ID        @chloe:chlo.ee               (the account we sync as)
    MATRIX_TOKEN          <access token for that account>
    LLAMA_URL             http://ai.servers.stgt.chlo.ee:8080
Optional (defaulted by the systemd unit):
    LLAMA_MODEL           gemma-4-12b
    FFMPEG                /path/to/ffmpeg
    LOCAL_SERVER          chlo.ee
    STATE_DIR             /var/lib/matrix-voicebot

Draft-reply (optional; the feature is inert unless MATRIX_DRAFTS_ROOM is set):
    MATRIX_DRAFTS_ROOM    !room:chlo.ee   an UNBRIDGED room the bot posts drafts
                          into. Must NOT be a bridge portal — drafts must never
                          reach a contact.
    DRAFT_IDLE_SECONDS    debounce before drafting after the last inbound msg (20)

Voice commands (optional; inert unless MATRIX_LILLY_DM_ROOM is set):
    MATRIX_LILLY_DM_ROOM  !room:chlo.ee   the DM room shared with the Lilly
                          assistant. A voice memo YOU send there is transcribed
                          — NOT summarised — and the plain transcript is posted
                          back into that same room as you, prefixed 🎙️; Lilly's
                          core service then reads it like any typed message and
                          answers it, giving you a voice-command path into Lilly.

When someone messages you in ANY chlo.ee-hosted room (same scope as the memo
summaries; the drafts room itself is excluded), after a short idle the bot pages
back through that room, uses YOUR own past messages there as a per-contact style
corpus + the recent thread as context, has llama draft a reply in your voice, and
posts it into MATRIX_DRAFTS_ROOM. If you've barely written in that room (cold
start), the style corpus is topped up from your messages across your other rooms
(sampled once, then cached).

By default nothing is relayed to the contact — you copy the draft yourself. But
you can APPROVE a draft: react to it with 👍 in the drafts room and the bot
relays that draft's text out into the original chat as you (the one path that
reaches a real contact, gated on your explicit reaction). Each draft carries a
DRAFT_META_KEY content field naming its source chat, since m.relates_to is
room-scoped and can't link the drafts room to the portal.

Compose requests
-----------------
The Lilly assistant can also file a compose request: a COMPOSE_META_KEY event
posted into the drafts room asking for a message to be sent to a named
contact. The bot resolves the contact by matching room members' display names,
drafts the message in the user's per-contact voice (same style-corpus + recent
context machinery as the draft-reply feature) and posts it as a normal
👍-to-send draft. As with every draft, nothing is ever sent without the
reaction.
"""

import asyncio
import base64
import datetime
import glob
import html
import logging
import os
import re
import subprocess
import sys
import tempfile
import time

import aiohttp
from nio import (
    AsyncClient,
    AsyncClientConfig,
    KeyVerificationAccept,
    KeyVerificationCancel,
    KeyVerificationEvent,
    KeyVerificationKey,
    KeyVerificationMac,
    KeyVerificationStart,
    LocalProtocolError,
    MatrixRoom,
    MessageDirection,
    RoomEncryptedAudio,
    RoomMessageAudio,
    RoomMessageText,
    ToDeviceMessage,
    UnknownEvent,
    UnknownToDeviceEvent,
)
from nio.crypto import decrypt_attachment

# matrix-nio doesn't parse m.reaction into a typed event in every version; when
# it does it's ReactionEvent, otherwise the reaction arrives as an UnknownEvent.
# We register for both and read the reaction from the raw `.source` either way.
try:
    from nio import ReactionEvent
except ImportError:  # older nio
    ReactionEvent = None

log = logging.getLogger("voicebot")

HOMESERVER = os.environ["MATRIX_HOMESERVER"]
USER_ID = os.environ["MATRIX_USER_ID"]
TOKEN = os.environ["MATRIX_TOKEN"]
LLAMA_URL = os.environ["LLAMA_URL"].rstrip("/")
LLAMA_MODEL = os.environ.get("LLAMA_MODEL", "gemma-4-12b")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
LOCAL_SERVER = os.environ.get("LOCAL_SERVER", USER_ID.split(":", 1)[1])
STATE_DIR = os.environ.get("STATE_DIR", "/var/lib/matrix-voicebot")

# Optional; when BOTH are set, drafts + status notices posted into the drafts
# room are sent as this account (Lilly) instead of the primary account. The
# primary account still does the sync, the memo summaries and any approved
# sends. If only one of the two is set, main() treats it as a config error.
MATRIX_LILLY_USER_ID = os.environ.get("MATRIX_LILLY_USER_ID", "")
MATRIX_LILLY_TOKEN = os.environ.get("MATRIX_LILLY_TOKEN", "")

# Optional; the DM room shared with the Lilly assistant. A voice memo YOU send
# there is transcribed and the transcript is posted back into the room (as you,
# prefixed 🎙️) instead of summarised — Lilly's core service then picks it up as
# a normal chat message and acts on it ("voice commands"). Inert when unset.
MATRIX_LILLY_DM_ROOM = os.environ.get("MATRIX_LILLY_DM_ROOM", "")

# ── Draft-reply feature (optional; inert unless DRAFTS_ROOM is set) ───────────
# When someone messages you in ANY chlo.ee-hosted room (same scope as the memo
# summaries), the bot drafts a reply in YOUR voice and posts it into DRAFTS_ROOM
# — a private, UNBRIDGED chlo.ee room. It NEVER posts into the portal, so a draft
# is never relayed to the contact; you read it and copy it into the real chat
# yourself. The drafts room is itself excluded (it's chlo.ee-hosted too).
DRAFTS_ROOM = os.environ.get("MATRIX_DRAFTS_ROOM", "")  # !room:chlo.ee (unbridged)
# Debounce: wait this long after the last inbound message before drafting, so a
# burst of messages yields ONE draft against the settled conversation.
DRAFT_IDLE_SECONDS = int(os.environ.get("DRAFT_IDLE_SECONDS", "20"))

# React to a draft in the drafts room with 👍 (thumbs-up, any skin tone / with or
# without the variation selector) to APPROVE it: the bot then relays the draft's
# text out into the original chat as you. This is the one path that sends to a
# real contact, gated on your explicit reaction.
APPROVE_EMOJI = "\U0001f44d"
# Custom content field embedded in each posted draft so a 👍 can resolve which
# chat to send to (m.relates_to is room-scoped and can't point across rooms).
DRAFT_META_KEY = "ee.chlo.voicebot.draft"
# Content field of a compose REQUEST posted into the drafts room (by the Lilly
# assistant's compose_message tool, as @lilly): {"contact": <name>,
# "instruction": <what the message should convey>}. The bot answers it with a
# regular draft.
COMPOSE_META_KEY = "ee.chlo.lilly.compose"

# Prefix that marks the message as an automated bot summary. Plain text + a
# leading emoji so it stays legible after every bridge's markup conversion.
BOT_PREFIX = "\U0001f916 Auto-summary (bot):"

# mautrix bridges append a per-network tag to a puppet's display name, e.g.
# "Chloe (WA)" / "Chloe (Telegram)" / "Chloe (Signal)". Strip a trailing one so
# the summary uses just the person's name.
BRIDGE_TAG_RE = re.compile(
    r"\s*\((?:WA|WhatsApp|Telegram|TG|Signal|SG)\)\s*$", re.IGNORECASE)

# Gemma 4 caps audio at 30 s/request; 28 keeps a margin.
CHUNK_SECONDS = 28
# Runaway guard. 70 * 28 s ≈ 32.7 min, so 30-minute memos are covered with a
# little margin; longer clips are truncated to the first MAX_CHUNKS chunks.
MAX_CHUNKS = 70
# Memos longer than this many chunks (5 * 28 s ≈ 2.3 min) are summarised as a
# bullet list instead of a 2-4 sentence prose blurb.
BULLET_THRESHOLD_CHUNKS = 5

TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim. Output only the transcription text, "
    "with no preamble, commentary or quotation marks."
)
# Folded into a single user turn (NOT a system message): Gemma's chat template
# has no system role — passing one yields a degenerate prompt and an empty
# completion. The transcript is appended after this instruction.
# `{speaker}` is filled in per-memo with the sender's display name (including for
# your own memos — the summary is read by the others in the chat), so it names
# the person instead of "the speaker".
SUMMARY_INSTRUCTION = (
    "You summarise voice memos. This memo was sent by {speaker}. Given the "
    "transcript below, reply with a concise summary (2-4 sentences) capturing the "
    "key points and any questions, decisions or action items. Refer to the sender "
    "by name ({speaker}) rather than \"the speaker\". Write the summary in the "
    "SAME LANGUAGE as the transcript. Reply with only the summary.\n\nTranscript:\n"
)
# Used for long memos: a bullet list instead of prose. Plain-text "• " bullets
# (one per line) survive every bridge's markup conversion.
BULLET_INSTRUCTION = (
    "You summarise voice memos. This memo was sent by {speaker} and is fairly "
    "long. Given the transcript below, reply with the summary as a list of bullet "
    "points — one per key point, question, decision or action item. Start each "
    "bullet with \"• \" on its own line. Refer to the sender by name ({speaker}) "
    "rather than \"the speaker\". Write in the SAME LANGUAGE as the transcript. "
    "Reply with only the bullet points.\n\nTranscript:\n"
)

# ── Draft-reply tuning ───────────────────────────────────────────────────────
# How much room history to page back for context + style corpus.
DRAFT_HISTORY_FETCH = 120
# How many of YOUR own past messages in the room to show the model as style
# examples (the per-contact "this is how Chloe writes to this person" signal).
DRAFT_STYLE_EXAMPLES = 40
# How many of the most recent messages (both sides) to include as the thread the
# reply responds to.
DRAFT_CONTEXT_MESSAGES = 16
# Cold start: if the room has fewer than this many of your own messages to learn
# from, top the style corpus up from your messages across your OTHER rooms, so a
# barely-used room doesn't collapse to generic-assistant tone.
MIN_STYLE_EXAMPLES = 8
# That cross-room corpus is built lazily and cached this long (seconds) — it's
# not rebuilt per draft.
GLOBAL_CORPUS_TTL = 1800
# Bounds on building it (caps the burst of /messages calls it costs).
GLOBAL_SAMPLE_ROOMS = 20
GLOBAL_PER_ROOM = 40
# The reply is drafted in YOUR voice. Gemma has no system role, so this is one
# user turn: instruction, then STYLE EXAMPLES (your past messages), then the
# recent CONVERSATION. `{me}`/`{other}` are the two display names.
DRAFT_INSTRUCTION = (
    "You draft a text-message reply that {me} will send to {other} in a private "
    "one-to-one chat. Write ONLY the message text {me} would send — in {me}'s own "
    "voice, closely matching the tone, length, punctuation, capitalisation, emoji "
    "use and typical phrasing shown in the STYLE EXAMPLES below (these are real "
    "past messages {me} wrote). Keep it natural and about as long as {me}'s usual "
    "messages — do not be more formal or more verbose than the examples. Reply in "
    "the SAME LANGUAGE as the conversation. Output only the reply text, with no "
    "quotation marks, no name label and no explanation.\n\n"
)
# The Lilly assistant can ask the bot to compose (not send) a message to a
# named contact. Same one-user-turn shape as DRAFT_INSTRUCTION, but framed
# around a REQUEST from {me} rather than a reply to {other}.
COMPOSE_INSTRUCTION = (
    "You draft a text message that {me} will send to {other} in a private "
    "chat. {me} asked their assistant to have a message sent to {other}; the "
    "message must convey the following, expressed in {me}'s own words:\n"
    "REQUEST: {instruction}\n\n"
    "Write ONLY the message text {me} would send — in {me}'s own voice, "
    "closely matching the tone, length, punctuation, capitalisation and "
    "emoji use shown in the STYLE EXAMPLES below (real past messages {me} "
    "wrote). Keep it natural and about as long as {me}'s usual messages. "
    "Write in the SAME LANGUAGE {me} and {other} use in the CONVERSATION "
    "below. Output only the message text, with no quotation marks, no name "
    "label and no explanation.\n\n"
)


def server_of(matrix_id: str) -> str:
    """Return the server_name part of a Matrix id (@user:server or !room:server)."""
    return matrix_id.split(":", 1)[1] if ":" in matrix_id else ""


async def llama_chat(session: aiohttp.ClientSession, messages, max_tokens: int,
                     temperature: float = 0.2, extra: dict = None) -> str:
    """POST an OpenAI-style chat completion to the ai host and return the text."""
    body = {
        "model": LLAMA_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra:
        body.update(extra)  # e.g. repeat_penalty (a llama.cpp extension)
    async with session.post(
        f"{LLAMA_URL}/v1/chat/completions",
        json=body,
        timeout=aiohttp.ClientTimeout(total=600),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
    choice = data["choices"][0]
    content = (choice["message"].get("content") or "").strip()
    if not content:
        log.warning("llama-server returned empty content (finish_reason=%s)",
                    choice.get("finish_reason"))
    return content


async def transcribe_chunk(session: aiohttp.ClientSession, wav_path: str) -> str:
    with open(wav_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": TRANSCRIBE_PROMPT},
                {"type": "input_audio",
                 "input_audio": {"data": b64, "format": "wav"}},
            ],
        }
    ]
    # A 28 s chunk is at most a few hundred tokens; cap at 1024 so a runaway
    # repetition loop on the audio path (which the peg-gemma4 parser then returns
    # as EMPTY) can't burn the full budget. repeat_penalty discourages the loop.
    text = await llama_chat(session, messages, max_tokens=1024,
                            extra={"repeat_penalty": 1.1})
    if not text:
        # Empty means the transcription degenerated into a loop and hit the cap;
        # retry once with more randomness + a stronger penalty to break it.
        log.warning("empty transcription; retrying with anti-loop sampling")
        text = await llama_chat(session, messages, max_tokens=1024,
                                temperature=0.6, extra={"repeat_penalty": 1.3})
    return text


def split_audio(raw: bytes, workdir: str):
    """Decode arbitrary input audio to 16 kHz mono WAV chunks; return paths."""
    src = os.path.join(workdir, "in")
    with open(src, "wb") as fh:
        fh.write(raw)
    pattern = os.path.join(workdir, "chunk_%03d.wav")
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
         "-ar", "16000", "-ac", "1",
         "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
         "-c:a", "pcm_s16le", pattern],
        check=True,
    )
    return sorted(glob.glob(os.path.join(workdir, "chunk_*.wav")))


async def download_media(session: aiohttp.ClientSession, mxc: str) -> bytes:
    """Fetch an mxc:// via the authenticated media endpoint (Synapse >=1.100)."""
    assert mxc.startswith("mxc://"), mxc
    server, media_id = mxc[len("mxc://"):].split("/", 1)
    url = f"{HOMESERVER}/_matrix/client/v1/media/download/{server}/{media_id}"
    async with session.get(
        url,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=aiohttp.ClientTimeout(total=120),
    ) as resp:
        resp.raise_for_status()
        return await resp.read()


class VoiceBot:
    def __init__(self, client: AsyncClient, http: aiohttp.ClientSession,
                drafts_client: AsyncClient = None):
        self.client = client
        self.http = http
        # The client that posts into the drafts room (Lilly's account when
        # configured via MATRIX_LILLY_USER_ID/MATRIX_LILLY_TOKEN, else falls
        # back to the primary account).
        self.drafts_client = drafts_client or client
        # room_id -> the pending debounced-draft asyncio.Task for that room.
        self._draft_tasks: dict = {}
        # Cached cross-room style corpus (your messages everywhere) + its build
        # time, for the cold-start top-up. See _global_style_corpus.
        self._global_style: list = []
        self._global_style_at: float = 0.0
        # Draft event_id (in the drafts room) -> (source_room_id,
        # source_event_id, text), so a 👍 approval knows what to send where.
        # Populated as we post; a durable copy also lives in each draft's content.
        self._drafts: dict = {}
        # Draft event_ids already sent, so a repeated/duplicate 👍 can't resend.
        self._sent_drafts: set = set()

    async def fetch_audio(self, event) -> bytes:
        """Download the memo, decrypting the attachment if the room is encrypted.

        RoomMessageAudio (plaintext room) → `url` is the media directly.
        RoomEncryptedAudio (E2EE room, event already decrypted by nio) → `url`
        points at the ciphertext and `key`/`hashes`/`iv` decrypt it.
        """
        mxc = getattr(event, "url", None)
        if not mxc:
            raise RuntimeError("audio event has no media url")
        data = await download_media(self.http, mxc)
        key = getattr(event, "key", None)
        if key:
            data = decrypt_attachment(
                data, key["k"], event.hashes["sha256"], event.iv,
            )
        return data

    def speaker_name(self, room: MatrixRoom, event) -> str:
        """Human name for the memo's sender — used so the summary names them.

        The sender's raw display name (for a bridged ghost this is the
        WhatsApp/Signal/Telegram contact's name; for your own memos, your own
        name — the summary is read by the other people in the chat, so never
        "you"), with any mautrix "(WA)"/"(Telegram)"/"(Signal)" tag stripped;
        falls back to the bare mxid if no display name is known.
        """
        user = room.users.get(event.sender)
        name = (user.display_name if user else None) \
            or room.user_name(event.sender) or event.sender
        return BRIDGE_TAG_RE.sub("", name).strip() or name

    async def on_audio(self, room: MatrixRoom, event):
        # Any voice memo in a chlo.ee-hosted room — ones you receive AND ones you
        # send yourself. (The reply is m.text, never m.audio, so no loop.)
        # Handles both RoomMessageAudio (plaintext) and RoomEncryptedAudio (E2EE).
        if server_of(room.room_id) != LOCAL_SERVER:
            return
        # Voice command: a memo YOU send in the Lilly DM room is transcribed and
        # posted back as plain text (as you) — Lilly's core service reads the
        # room and answers it like a typed message. No summary in this room.
        if MATRIX_LILLY_DM_ROOM and room.room_id == MATRIX_LILLY_DM_ROOM:
            if event.sender != USER_ID:
                return
            log.info("voice command memo in the Lilly DM room")
            try:
                raw = await self.fetch_audio(event)
                transcript, _ = await self.transcribe(raw)
            except Exception:
                log.exception("failed to transcribe a voice command")
                return
            await self.post_transcript(room, event, transcript)
            return
        log.info("voice memo in %s from %s", room.room_id, event.sender)
        try:
            raw = await self.fetch_audio(event)
            summary = await self.summarise(raw, self.speaker_name(room, event))
        except Exception:
            log.exception("failed to summarise a memo in %s", room.room_id)
            return
        await self.post_summary(room, event, summary)

    async def transcribe(self, raw: bytes):
        """Chunk the audio and transcribe it; returns (transcript, chunk_count)."""
        with tempfile.TemporaryDirectory(prefix="voicebot-") as workdir:
            chunks = split_audio(raw, workdir)
            if not chunks:
                raise RuntimeError("ffmpeg produced no chunks")
            if len(chunks) > MAX_CHUNKS:
                log.warning("clip has %d chunks; capping at %d", len(chunks), MAX_CHUNKS)
                chunks = chunks[:MAX_CHUNKS]
            parts = []
            for i, wav in enumerate(chunks):
                log.info("transcribing chunk %d/%d", i + 1, len(chunks))
                parts.append(await transcribe_chunk(self.http, wav))
        transcript = " ".join(p for p in parts if p).strip()
        if not transcript:
            raise RuntimeError("empty transcript")
        log.info("transcript: %d chars", len(transcript))
        return transcript, len(chunks)

    async def summarise(self, raw: bytes, speaker: str) -> str:
        transcript, chunk_count = await self.transcribe(raw)
        template = (BULLET_INSTRUCTION if chunk_count > BULLET_THRESHOLD_CHUNKS
                    else SUMMARY_INSTRUCTION)
        instruction = template.format(speaker=speaker)
        msgs = [{"role": "user", "content": f"{instruction}{transcript}"}]
        # Just a ceiling (the model stops at end_of_turn when the summary is
        # done), set high so a long-memo bullet list is never truncated: the
        # peg-gemma4 chat parser returns EMPTY content if the turn is cut off at
        # max_tokens before it's grammatically complete (finish_reason=length).
        summary = await llama_chat(self.http, msgs, max_tokens=8192)
        if not summary:
            log.warning("empty summary; retrying with anti-loop sampling")
            summary = await llama_chat(self.http, msgs, max_tokens=8192,
                                       temperature=0.6, extra={"repeat_penalty": 1.2})
        if not summary:
            # Genuinely nothing to condense (e.g. a very short memo) — post the
            # transcript instead, truncated so a long memo can't dump a wall of
            # text into the chat.
            log.warning("summary still empty; falling back to the transcript")
            summary = transcript if len(transcript) <= 1000 else transcript[:1000] + " […]"
        return summary

    async def post_summary(self, room: MatrixRoom, event, summary: str):
        # Reply to the memo (m.in_reply_to) so the bridge attaches it as a quote
        # on the remote side. m.text, prefixed as a bot summary — sent as @chloe
        # so mautrix relays it OUT to the messenger.
        # Label on its own line so a bullet-list (or multi-line) summary reads
        # cleanly; \n survives in the plain body, and becomes <br> in the HTML.
        body = f"{BOT_PREFIX}\n{summary}"
        formatted = ("\U0001f916 <b>Auto-summary (bot):</b><br>"
                     + html.escape(summary).replace("\n", "<br>"))
        content = {
            "msgtype": "m.text",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted,
            "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
        }
        # In an E2EE room nio encrypts this automatically; ignore_unverified_devices
        # lets it send to the room's unverified devices (otherwise it refuses).
        # No-op in a plaintext bridge portal.
        await self.client.room_send(
            room.room_id, message_type="m.room.message", content=content,
            ignore_unverified_devices=True,
        )

    async def post_transcript(self, room: MatrixRoom, event, transcript: str):
        """Post a plain transcript into the Lilly DM room, as the primary account.

        Posted as the primary account into the DM room so the Lilly assistant
        treats it as user input; the 🎙️ marks it as a transcription in the room
        history.
        """
        body = f"\U0001f399️ {transcript}"
        formatted = ("\U0001f399️ "
                     + html.escape(transcript).replace("\n", "<br>"))
        content = {
            "msgtype": "m.text",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted,
            "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
        }
        await self.client.room_send(
            room.room_id, message_type="m.room.message", content=content,
            ignore_unverified_devices=True,
        )

    # ── Draft-reply ──────────────────────────────────────────────────────────
    async def on_text(self, room: MatrixRoom, event):
        """Debounced trigger for the draft-reply feature.

        Fires on every m.text. We act in any chlo.ee-hosted room (same scope as
        the memo summaries), except the drafts room itself. A message from the
        OTHER person (re)starts an idle timer; a message from YOU cancels it
        (you're handling the reply yourself). Nothing is ever sent into `room` —
        the draft goes only to the unbridged DRAFTS_ROOM.
        """
        if not DRAFTS_ROOM:
            return
        if room.room_id == DRAFTS_ROOM:
            # A compose request from the Lilly assistant is handled; all other
            # drafts-room chatter is ignored (never drafted against).
            if (event.source.get("content") or {}).get(COMPOSE_META_KEY):
                asyncio.create_task(self._handle_compose(room, event))
            return
        if server_of(room.room_id) != LOCAL_SERVER:
            return
        if event.sender == USER_ID:
            self._cancel_draft(room.room_id)  # you spoke — drop any pending draft
            return
        # Lilly's own chat messages (e.g. in the DM room with her user) must not
        # trigger drafts — she is not a contact to reply to.
        if MATRIX_LILLY_USER_ID and event.sender == MATRIX_LILLY_USER_ID:
            return
        self._cancel_draft(room.room_id)
        self._draft_tasks[room.room_id] = asyncio.create_task(
            self._draft_after_idle(room))

    def _cancel_draft(self, room_id: str):
        task = self._draft_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()

    async def _draft_after_idle(self, room: MatrixRoom):
        try:
            await asyncio.sleep(DRAFT_IDLE_SECONDS)
            await self._make_draft(room)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("draft failed for %s", room.room_id)
        finally:
            self._draft_tasks.pop(room.room_id, None)

    async def _recent_text(self, room: MatrixRoom, limit: int):
        """Page back through `room` and return recent m.text events, oldest-first."""
        resp = await self.client.room_messages(
            room.room_id, start=self.client.next_batch,
            direction=MessageDirection.back, limit=limit)
        chunk = getattr(resp, "chunk", None)
        if chunk is None:
            log.warning("room_messages failed for %s: %s", room.room_id, resp)
            return []
        # /messages dir=back yields newest-first; reverse to chronological order.
        return [e for e in reversed(chunk)
                if isinstance(e, RoomMessageText) and (e.body or "").strip()]

    def _own_messages(self, events) -> list:
        """Your own outbound text from a list of events, bot summaries excluded.

        The bot's own auto-summaries are sent as you (@chloe) and start with the
        BOT_PREFIX robot emoji — filter them so they don't pollute the style
        signal with machine-written text.
        """
        return [e.body.strip() for e in events
                if e.sender == USER_ID and not e.body.startswith("\U0001f916")]

    async def _global_style_corpus(self) -> list:
        """Your recent messages sampled across ALL your rooms, cached.

        The cold-start fallback: when the target room has too little of your
        writing to learn from, this supplies your general voice. Built lazily by
        paging a bounded number of rooms and cached for GLOBAL_CORPUS_TTL so it
        costs a burst of /messages calls at most once every half hour.
        """
        now = time.monotonic()
        if self._global_style and (now - self._global_style_at) < GLOBAL_CORPUS_TTL:
            return self._global_style
        corpus: list = []
        sampled = 0
        for room in self.client.rooms.values():
            if sampled >= GLOBAL_SAMPLE_ROOMS or len(corpus) >= DRAFT_STYLE_EXAMPLES:
                break
            if room.room_id == DRAFTS_ROOM:
                continue
            sampled += 1
            try:
                events = await self._recent_text(room, GLOBAL_PER_ROOM)
            except Exception:
                log.exception("global corpus: failed to page %s", room.room_id)
                continue
            corpus.extend(self._own_messages(events))
        if corpus:
            self._global_style = corpus[-DRAFT_STYLE_EXAMPLES:]
            self._global_style_at = now
            log.info("built global style corpus: %d messages from %d rooms",
                     len(self._global_style), sampled)
        return self._global_style

    async def _style_examples(self, room: MatrixRoom, events) -> list:
        """Your past messages as a style corpus: in-room first, cold-start top-up."""
        # Style corpus: YOUR past messages in this room (per-contact voice).
        in_room = self._own_messages(events)[-DRAFT_STYLE_EXAMPLES:]
        yours = in_room
        # Cold start: too little of your writing in this room → top up from your
        # voice across other rooms. In-room examples go LAST (closest to the
        # instruction, so the model weights the per-contact tone most); dedup
        # keeps the in-room copy of any shared line.
        if len(in_room) < MIN_STYLE_EXAMPLES:
            general = await self._global_style_corpus()
            seen = set(in_room)
            merged = [m for m in general if m not in seen] + in_room
            yours = merged[-DRAFT_STYLE_EXAMPLES:]
            log.info("cold start in %s (%d in-room); topped up to %d examples",
                     room.room_id, len(in_room), len(yours))
        return yours

    async def _make_draft(self, room: MatrixRoom):
        events = await self._recent_text(room, DRAFT_HISTORY_FETCH)
        if not events:
            return
        # If your own message is the most recent, you already replied — skip.
        if events[-1].sender == USER_ID:
            return
        # Own display name, preferring the raw one from room.users (room.user_name
        # can add a "(@mxid)" disambiguation tag), falling back to the localpart.
        me_user = room.users.get(USER_ID)
        me = (me_user.display_name if me_user else None) \
            or USER_ID.split(":", 1)[0].lstrip("@")
        me = BRIDGE_TAG_RE.sub("", me).strip() or me
        other = self.speaker_name(room, events[-1])
        yours = await self._style_examples(room, events)
        convo = events[-DRAFT_CONTEXT_MESSAGES:]

        def label(e):
            return me if e.sender == USER_ID else self.speaker_name(room, e)

        style_block = ("STYLE EXAMPLES (real past messages written by "
                       f"{me}):\n" + "\n".join(f"- {m}" for m in yours) + "\n\n"
                       ) if yours else ""
        convo_block = ("CONVERSATION so far (most recent last):\n"
                       + "\n".join(f"{label(e)}: {e.body.strip()}" for e in convo))
        prompt = (DRAFT_INSTRUCTION.format(me=me, other=other)
                  + style_block + convo_block + f"\n\nReply as {me}:")
        # A bit more temperature than the summary path: a reply should sound
        # natural, not deterministic. repeat_penalty guards the same loop bug.
        # max_tokens is just a ceiling (the model stops at end_of_turn when done);
        # set high because peg-gemma4 returns EMPTY content if the turn is cut off
        # at the cap before it's grammatically complete (finish_reason=length).
        msgs = [{"role": "user", "content": prompt}]
        draft = await llama_chat(self.http, msgs, max_tokens=2048,
                                 temperature=0.7, extra={"repeat_penalty": 1.1})
        if not draft:
            # Empty = hit the cap (often a repetition loop). Retry once with
            # anti-loop sampling to break it, same as the summary path.
            log.warning("empty draft for %s; retrying with anti-loop sampling",
                        room.room_id)
            draft = await llama_chat(self.http, msgs, max_tokens=2048,
                                     temperature=0.6, extra={"repeat_penalty": 1.3})
        if not draft:
            log.warning("draft still empty for %s; skipping", room.room_id)
            return
        await self._post_draft(room, other, events[-1], draft)

    async def _post_draft(self, room: MatrixRoom, other: str, source_event,
                          draft: str):
        """Post a draft into DRAFTS_ROOM (never into the portal).

        Carries a DRAFT_META_KEY field with the source room + event + text so a
        later 👍 in the drafts room can relay this exact draft to the right chat.
        """
        quoted = (source_event.body or "").strip()
        if len(quoted) > 300:
            quoted = quoted[:300] + " […]"
        header = f"✏️ Draft reply to {other} — 👍 to send"
        body = f"{header}\n(re: {quoted})\n\n{draft}"
        formatted = (f"✏️ <b>Draft reply to {html.escape(other)}</b> — 👍 to send<br>"
                     f"<i>re: {html.escape(quoted)}</i><br><br>"
                     + html.escape(draft).replace("\n", "<br>"))
        content = {
            "msgtype": "m.text",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted,
            DRAFT_META_KEY: {
                "source_room_id": room.room_id,
                "source_event_id": source_event.event_id,
                "text": draft,
            },
        }
        resp = await self.drafts_client.room_send(
            DRAFTS_ROOM, message_type="m.room.message", content=content,
            ignore_unverified_devices=True,
        )
        ev_id = getattr(resp, "event_id", None)
        if ev_id:
            self._drafts[ev_id] = (room.room_id, source_event.event_id, draft)
        log.info("posted draft reply to %s into drafts room", other)

    # ── Compose requests (Lilly assistant asks for a message to a contact) ────
    async def _handle_compose(self, room: MatrixRoom, event):
        """Answer a compose request: resolve the contact, draft in the user's
        per-contact voice, post as a normal 👍-to-send draft. Never sends
        anything itself.
        """
        try:
            allowed = event.sender == USER_ID or (
                MATRIX_LILLY_USER_ID and event.sender == MATRIX_LILLY_USER_ID)
            if not allowed:
                log.warning("ignoring compose request from unauthorised sender %s",
                            event.sender)
                return
            meta = (event.source.get("content") or {}).get(COMPOSE_META_KEY) or {}
            contact = (meta.get("contact") or "").strip()
            instruction = (meta.get("instruction") or "").strip()
            if not contact or not instruction:
                await self._notify_drafts(
                    "⚠️ Compose request missing contact or instruction.",
                    reply_to=event.event_id)
                return
            matches = self._find_contact_room(contact)
            if not matches:
                await self._notify_drafts(f"⚠️ No chat found for '{contact}'.",
                                          reply_to=event.event_id)
                return
            if len(matches) > 1:
                # "Write Mama" while Mama is in her 1:1 chat AND the family
                # group means the 1:1 chat: when exactly one direct (2-member)
                # room matches, take it. Otherwise it's genuinely ambiguous
                # (e.g. two different people with the same name).
                direct = [m for m in matches if len(m[0].users) == 2]
                if len(direct) == 1:
                    matches = direct
                else:
                    names = ", ".join(f"{disp} ({len(r.users)} members)"
                                      for r, disp in matches)
                    await self._notify_drafts(
                        f"⚠️ '{contact}' is ambiguous: {names} — be more specific.",
                        reply_to=event.event_id)
                    return
            target_room, other = matches[0]
            events = await self._recent_text(target_room, DRAFT_HISTORY_FETCH)
            # Own display name, same derivation as _make_draft, against the
            # target room.
            me_user = target_room.users.get(USER_ID)
            me = (me_user.display_name if me_user else None) \
                or USER_ID.split(":", 1)[0].lstrip("@")
            me = BRIDGE_TAG_RE.sub("", me).strip() or me
            yours = await self._style_examples(target_room, events)
            convo = events[-DRAFT_CONTEXT_MESSAGES:]

            def label(e):
                return me if e.sender == USER_ID else self.speaker_name(target_room, e)

            style_block = ("STYLE EXAMPLES (real past messages written by "
                           f"{me}):\n" + "\n".join(f"- {m}" for m in yours) + "\n\n"
                           ) if yours else ""
            convo_block = ("CONVERSATION so far (most recent last):\n"
                           + "\n".join(f"{label(e)}: {e.body.strip()}" for e in convo)
                           ) if convo else ""
            prompt = (COMPOSE_INSTRUCTION.format(me=me, other=other, instruction=instruction)
                      + style_block + convo_block + f"\n\nMessage from {me} to {other}:")
            msgs = [{"role": "user", "content": prompt}]
            draft = await llama_chat(self.http, msgs, max_tokens=2048,
                                     temperature=0.7, extra={"repeat_penalty": 1.1})
            if not draft:
                log.warning("empty compose draft to %s; retrying with anti-loop sampling",
                            other)
                draft = await llama_chat(self.http, msgs, max_tokens=2048,
                                         temperature=0.6, extra={"repeat_penalty": 1.3})
            if not draft:
                await self._notify_drafts(
                    f"⚠️ Could not draft a message for '{contact}'.",
                    reply_to=event.event_id)
                return
            await self._post_compose_draft(target_room, other, instruction, draft)
        except Exception:
            log.exception("compose request failed")

    def _find_contact_room(self, name: str) -> list:
        """Resolve a contact name to chat rooms.

        Matches the display names of room members (excluding the user and
        Lilly) across LOCAL_SERVER-hosted rooms, mautrix bridge tags stripped.
        Exact (case-insensitive) matches beat substring matches; among equal
        matches, rooms with fewer members (1:1 chats) come first. Returns a
        list of (room, display_name) — empty, one, or several (ambiguous).
        """
        needle = name.strip().casefold()
        if not needle:
            return []
        exact: dict = {}
        partial: dict = {}
        for room in self.client.rooms.values():
            if room.room_id in (DRAFTS_ROOM, MATRIX_LILLY_DM_ROOM):
                continue
            if server_of(room.room_id) != LOCAL_SERVER:
                continue
            for uid, user in room.users.items():
                if uid == USER_ID or (MATRIX_LILLY_USER_ID and uid == MATRIX_LILLY_USER_ID):
                    continue
                disp = BRIDGE_TAG_RE.sub("", (user.display_name or uid)).strip()
                if not disp:
                    continue
                if disp.casefold() == needle:
                    exact[room.room_id] = (room, disp)
                elif needle in disp.casefold() and room.room_id not in exact:
                    partial.setdefault(room.room_id, (room, disp))
        chosen = list(exact.values()) if exact else list(partial.values())
        chosen.sort(key=lambda pair: len(pair[0].users))
        return chosen

    async def _post_compose_draft(self, target_room: MatrixRoom, other: str,
                                  instruction: str, draft: str):
        """Post a composed message as a normal draft into DRAFTS_ROOM — same
        DRAFT_META_KEY contract, so the existing 👍 approval sends it;
        source_event_id is None (nothing to reply to in the target chat).
        """
        quoted = instruction.strip()
        if len(quoted) > 300:
            quoted = quoted[:300] + " […]"
        header = f"✏️ Draft to {other} — requested via Lilly — 👍 to send"
        body = f"{header}\n(request: {quoted})\n\n{draft}"
        formatted = (f"✏️ <b>Draft to {html.escape(other)}</b> — requested via Lilly "
                     f"— 👍 to send<br><i>request: {html.escape(quoted)}</i><br><br>"
                     + html.escape(draft).replace("\n", "<br>"))
        content = {
            "msgtype": "m.text",
            "body": body,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted,
            DRAFT_META_KEY: {
                "source_room_id": target_room.room_id,
                "source_event_id": None,
                "text": draft,
            },
        }
        resp = await self.drafts_client.room_send(
            DRAFTS_ROOM, message_type="m.room.message", content=content,
            ignore_unverified_devices=True,
        )
        ev_id = getattr(resp, "event_id", None)
        if ev_id:
            self._drafts[ev_id] = (target_room.room_id, None, draft)
        log.info("posted composed draft to %s into drafts room", other)

    # ── Approval (👍 a draft → send it) ──────────────────────────────────────
    async def on_reaction(self, room: MatrixRoom, event):
        """A 👍 from you on a draft in the drafts room relays it to the chat.

        Parsed from the raw event source so it works whether nio delivers the
        reaction as ReactionEvent or UnknownEvent. Only YOUR 👍 in the drafts
        room counts; other reactions/senders/rooms are ignored.
        """
        if not DRAFTS_ROOM or room.room_id != DRAFTS_ROOM:
            return
        src = getattr(event, "source", None) or {}
        if src.get("type") != "m.reaction":
            return
        if getattr(event, "sender", None) != USER_ID:
            return  # only you approving counts
        rel = (src.get("content") or {}).get("m.relates_to") or {}
        if rel.get("rel_type") != "m.annotation":
            return
        # Thumbs-up in any form (bare, +variation-selector, +skin-tone).
        if not (rel.get("key") or "").startswith(APPROVE_EMOJI):
            return
        draft_id = rel.get("event_id")
        if not draft_id or draft_id in self._sent_drafts:
            return
        meta = self._drafts.get(draft_id) or await self._lookup_draft(draft_id)
        if not meta:
            log.warning("👍 on unknown draft %s (restart, or not a draft)", draft_id)
            return
        source_room_id, source_event_id, text = meta
        self._sent_drafts.add(draft_id)  # guard against a duplicate 👍
        try:
            await self._send_out(source_room_id, source_event_id, text)
        except Exception:
            self._sent_drafts.discard(draft_id)
            log.exception("failed to send approved draft %s", draft_id)
            await self._notify_drafts("⚠️ Failed to send that draft — see the log.",
                                      reply_to=draft_id)
            return
        await self._notify_drafts("✅ Sent.", reply_to=draft_id)

    async def _lookup_draft(self, draft_id: str):
        """Durable fallback: recover a draft's metadata from its stored event.

        Covers a 👍 that arrives after a restart (the in-memory map is empty).
        Works for a plaintext drafts room; an encrypted one may not expose the
        content here, in which case the in-memory map is the only path.
        """
        try:
            resp = await self.client.room_get_event(DRAFTS_ROOM, draft_id)
        except Exception:
            log.exception("room_get_event failed for %s", draft_id)
            return None
        ev = getattr(resp, "event", None)
        meta = ((getattr(ev, "source", None) or {}).get("content") or {}).get(DRAFT_META_KEY)
        if not meta:
            return None
        return (meta.get("source_room_id"), meta.get("source_event_id"),
                meta.get("text"))

    async def _send_out(self, room_id: str, reply_to_event_id, text: str):
        """Send the approved draft into the original chat AS YOU (relays out).

        Clean text — no bot prefix — as an m.text reply to the message it answers
        so the bridge attaches it as a quote on the remote side.
        """
        content = {"msgtype": "m.text", "body": text}
        if reply_to_event_id:
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to_event_id}}
        await self.client.room_send(
            room_id, message_type="m.room.message", content=content,
            ignore_unverified_devices=True,
        )
        log.info("sent approved draft into %s", room_id)

    async def _notify_drafts(self, text: str, reply_to=None):
        """Post a small status notice into the drafts room (never a portal)."""
        content = {"msgtype": "m.notice", "body": text}
        if reply_to:
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}
        await self.drafts_client.room_send(
            DRAFTS_ROOM, message_type="m.room.message", content=content,
            ignore_unverified_devices=True,
        )

    async def on_verification_request(self, event):
        """Answer Element's `m.key.verification.request` with `ready`.

        Modern Element verifies with the request→ready→start flow, but nio
        doesn't parse `m.key.verification.request` (it arrives as an
        UnknownToDeviceEvent) and so never replies — which is why clicking
        "Verify" in Element just hangs, and why a bot-initiated bare `.start`
        gets ignored. We reply `ready` here; Element then sends the SAS `.start`,
        which nio parses normally and `on_to_device` drives to completion.
        """
        if getattr(event, "type", "") != "m.key.verification.request":
            return
        if event.sender != self.client.user_id:
            return
        content = event.source.get("content", {})
        if "m.sas.v1" not in content.get("methods", []):
            return
        txid = content.get("transaction_id")
        from_device = content.get("from_device")
        if not txid or not from_device:
            return
        ready = ToDeviceMessage(
            "m.key.verification.ready",
            self.client.user_id,
            from_device,
            {
                "from_device": self.client.device_id,
                "methods": ["m.sas.v1"],
                "transaction_id": txid,
            },
        )
        await self.client.to_device(ready)
        log.info("answered verification request %s (from device %s)",
                 txid, from_device)

    async def on_to_device(self, event):
        """Drive an SAS (emoji) verification to completion, auto-confirming.

        Handles BOTH directions:
          • one the BOT started (`!voicebot verify`): the peer replies with
            `KeyVerificationAccept` → we send our key (`share_key`);
          • one the peer started: `KeyVerificationStart` → we accept + send key.
        Then `key` → confirm the SAS (no emoji comparison — own device, own
        server) and `mac` → send our MAC. Unknown/expired transactions are
        ignored.
        """
        client = self.client
        tx = getattr(event, "transaction_id", None)
        try:
            if isinstance(event, KeyVerificationStart):
                if "emoji" not in event.short_authentication_string:
                    await client.cancel_key_verification(tx, reject=True)
                    return
                await client.accept_key_verification(tx)
                await client.to_device(client.key_verifications[tx].share_key())
                log.info("accepted incoming verification %s", tx)
            elif isinstance(event, KeyVerificationAccept):
                # We started it; the peer accepted → send our public key.
                await client.to_device(client.key_verifications[tx].share_key())
                log.info("verification %s accepted by peer", tx)
            elif isinstance(event, KeyVerificationKey):
                # Auto-confirm the short auth string without comparing emoji.
                await client.confirm_short_auth_string(tx)
            elif isinstance(event, KeyVerificationMac):
                sas = client.key_verifications[tx]
                await client.to_device(sas.get_mac())
                # nio's SAS ends at the MAC step and NEVER sends
                # m.key.verification.done, but modern Element (Element X) waits
                # for it — otherwise it hangs on "waiting for your other device".
                # Send it ourselves to close the flow out.
                dev = sas.other_olm_device
                await client.to_device(ToDeviceMessage(
                    "m.key.verification.done", dev.user_id, dev.id,
                    {"transaction_id": tx}))
                log.info("verification %s complete (sent done)", tx)
            elif isinstance(event, KeyVerificationCancel):
                log.info("verification cancelled: %s", getattr(event, "reason", ""))
        except KeyError:
            log.info("verification event for unknown/expired tx %s", tx)
        except LocalProtocolError as e:
            log.info("verification %s protocol note: %s", tx, e)
        except Exception:
            log.exception("verification handler error")


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    os.makedirs(STATE_DIR, exist_ok=True)

    # Config error: MATRIX_LILLY_USER_ID and MATRIX_LILLY_TOKEN must be set
    # together (or not at all) — one without the other can't authenticate.
    if bool(MATRIX_LILLY_USER_ID) != bool(MATRIX_LILLY_TOKEN):
        log.error("MATRIX_LILLY_USER_ID and MATRIX_LILLY_TOKEN must both be set "
                  "(or both unset) — only one is set")
        return 1

    # nio expires an SAS verification if no event arrives within 1 minute (5 min
    # total) — too short when you have to notice and click "Accept" on the
    # incoming verification in Element. Widen both windows so a human-paced
    # verify completes instead of being cancelled mid-flow.
    from nio.crypto.sas import Sas
    Sas._max_event_timeout = datetime.timedelta(minutes=10)
    Sas._max_age = datetime.timedelta(minutes=30)

    # E2EE enabled: the crypto store (olm account + megolm sessions) lives under
    # STATE_DIR and persists across restarts. store_sync_tokens stays off — we
    # adopt next_batch by hand to skip backlog; the crypto state persists anyway.
    config = AsyncClientConfig(encryption_enabled=True, store_sync_tokens=False)
    client = AsyncClient(HOMESERVER, USER_ID, store_path=STATE_DIR, config=config)
    client.access_token = TOKEN
    client.user_id = USER_ID
    # The device_id MUST be the real device the token belongs to, so the keys we
    # upload are attributed to it and senders share room keys to the right device.
    who = await client.whoami()
    client.device_id = who.device_id
    log.info("running as %s on device %s", USER_ID, client.device_id)
    # Load (or create) the olm account in the store and publish our device keys.
    client.load_store()
    if client.should_upload_keys:
        await client.keys_upload()

    # Optional second, send-only client for Lilly's own account: no sync, no
    # E2EE store — the drafts room must be unencrypted for this (which the
    # draft-approval durable lookup, _lookup_draft, already recommends). If the
    # drafts room is E2EE, leave MATRIX_LILLY_* unset to fall back to the
    # primary account's encrypted path.
    lilly_client = None
    if MATRIX_LILLY_USER_ID and MATRIX_LILLY_TOKEN:
        lilly_client = AsyncClient(HOMESERVER, MATRIX_LILLY_USER_ID)
        lilly_client.access_token = MATRIX_LILLY_TOKEN
        lilly_client.user_id = MATRIX_LILLY_USER_ID
        lilly_who = await lilly_client.whoami()
        lilly_client.device_id = lilly_who.device_id
        log.info("drafts will be posted as %s (device %s)",
                 MATRIX_LILLY_USER_ID, lilly_client.device_id)

    async with aiohttp.ClientSession() as http:
        bot = VoiceBot(client, http, drafts_client=lilly_client)

        # Skip backlog: one sync just to advance next_batch, then adopt it so
        # sync_forever only ever delivers events newer than startup. full_state
        # so nio learns room members + device lists (needed to encrypt replies).
        first = await client.sync(timeout=5000, full_state=True)
        client.next_batch = first.next_batch
        log.info("adopted sync token; watching for voice memos (sent + received) "
                 "as %s", USER_ID)

        # Both plaintext (bridge portals) and decrypted-E2EE audio events.
        client.add_event_callback(bot.on_audio, (RoomMessageAudio, RoomEncryptedAudio))
        # Draft-reply trigger (inert unless MATRIX_DRAFTS_ROOM is set). Watches
        # text in every chlo.ee-hosted room except the drafts room.
        client.add_event_callback(bot.on_text, (RoomMessageText,))
        # 👍 on a draft in the drafts room → send it out. Register for both the
        # typed reaction (newer nio) and UnknownEvent (older); on_reaction reads
        # the raw source, so either delivery works.
        reaction_types = ((UnknownEvent,) if ReactionEvent is None
                          else (UnknownEvent, ReactionEvent))
        client.add_event_callback(bot.on_reaction, reaction_types)
        # Answer Element's verification REQUEST (so clicking "Verify" works)…
        client.add_to_device_callback(bot.on_verification_request, (UnknownToDeviceEvent,))
        # …then auto-accept/confirm the SAS start/key/mac that follows.
        client.add_to_device_callback(bot.on_to_device, (KeyVerificationEvent,))

        # sync_forever also handles ongoing key upload/query/claim for e2e.
        try:
            await client.sync_forever(timeout=30000, full_state=False)
        finally:
            if lilly_client is not None:
                await lilly_client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
