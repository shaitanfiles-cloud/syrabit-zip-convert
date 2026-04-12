#!/usr/bin/env python3
import os, asyncio, httpx, time, json, sys
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

SARVAM_KEYS = [
    os.environ.get('SARVAM_API_KEY', ''),
    os.environ.get('SARVAM_API_KEY_2', ''),
]
SARVAM_KEYS = [k for k in SARVAM_KEYS if k]

MONGO_URL = (os.environ.get('MONGO_URL') or '').strip().strip('"').strip("'")
DB_NAME = os.environ.get('DB_NAME', 'test_database')
MAX_CHUNK = 1800
key_index = 0
PROGRESS_FILE = "/tmp/translate_progress.json"

def get_key():
    global key_index
    return SARVAM_KEYS[key_index % len(SARVAM_KEYS)]

def rotate_key():
    global key_index
    key_index += 1
    print(f"  Rotated to key index {key_index % len(SARVAM_KEYS)}", flush=True)

async def translate_chunk(client, text, retries=3):
    text = text[:1950]
    payload = {
        "input": text,
        "source_language_code": "en-IN",
        "target_language_code": "as-IN",
        "speaker_gender": "Female",
        "mode": "formal",
        "model": "sarvam-translate:v1",
        "enable_preprocessing": False,
    }
    for attempt in range(retries):
        try:
            resp = await client.post("https://api.sarvam.ai/translate", json=payload,
                                      headers={"api-subscription-key": get_key()}, timeout=30)
            resp.raise_for_status()
            return resp.json().get("translated_text", "")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                rotate_key()
                if attempt < retries - 1:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
            if e.response.status_code == 400 and attempt < retries - 1:
                await asyncio.sleep(1)
                continue
            raise
    return ""

def split_to_chunks(text, max_len=MAX_CHUNK):
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(line) > max_len:
            if current:
                chunks.append(current)
                current = ""
            for j in range(0, len(line), max_len):
                chunks.append(line[j:j + max_len])
        elif len(current) + len(line) + 1 > max_len and current:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks

async def translate_text(client, text):
    chunks = split_to_chunks(text)
    parts = []
    for chunk in chunks:
        translated = await translate_chunk(client, chunk)
        parts.append(translated)
        await asyncio.sleep(0.15)
    return "\n".join(parts)

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)

async def main():
    mongo = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = mongo[DB_NAME]

    chapters = await db.chapters.find(
        {"content": {"$exists": True, "$ne": ""}},
        {"_id": 0, "id": 1, "title": 1, "content": 1, "content_as": 1}
    ).to_list(500)

    needs = []
    for ch in chapters:
        ca = ch.get("content_as", "")
        assamese_chars = sum(1 for c in (ca or "")[:500] if '\u0980' <= c <= '\u09FF')
        if assamese_chars < 10:
            needs.append(ch)

    print(f"Total: {len(chapters)}, Need translation: {len(needs)}", flush=True)

    if not needs:
        print("All done!", flush=True)
        mongo.close()
        return

    progress = {"ok": 0, "fail": 0, "skip": 0, "total": len(needs)}

    async with httpx.AsyncClient() as client:
        for i, ch in enumerate(needs):
            content = ch.get("content", "")
            title = ch.get("title", "")[:50]
            if not content or len(content.strip()) < 100:
                progress["skip"] += 1
                continue
            try:
                start = time.time()
                chunks = split_to_chunks(content)
                translated = await translate_text(client, content)
                elapsed = time.time() - start
                assamese_chars = sum(1 for c in translated[:300] if '\u0980' <= c <= '\u09FF')
                if translated and assamese_chars >= 5:
                    await db.chapters.update_one(
                        {"id": ch["id"]},
                        {"$set": {"content_as": translated, "content_as_generated_at": datetime.now(timezone.utc).isoformat()}}
                    )
                    progress["ok"] += 1
                    print(f"[{i+1}/{len(needs)}] OK {title} ({len(chunks)}ch, {len(translated.split())}w, {elapsed:.1f}s)", flush=True)
                else:
                    progress["fail"] += 1
                    print(f"[{i+1}/{len(needs)}] FAIL {title} (AS:{assamese_chars})", flush=True)
            except Exception as e:
                progress["fail"] += 1
                print(f"[{i+1}/{len(needs)}] ERR {title}: {str(e)[:100]}", flush=True)
                await asyncio.sleep(3)

            save_progress(progress)

    print(f"\n=== COMPLETE: {progress['ok']} ok, {progress['skip']} skip, {progress['fail']} fail ===", flush=True)
    save_progress(progress)
    mongo.close()

if __name__ == "__main__":
    asyncio.run(main())
