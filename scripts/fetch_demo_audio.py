"""data/demo_tracks.json 의 곡을 Drive에서 내려 mp3로 변환하고 R2에 올린다.

파이프라인 (계획서 10.1):
    Drive(wav, 임의 파일명)
      → rclone backend copyid drive: {file_id}   # 파일 ID 단위 다운로드
      → ffmpeg -b:a 128k → {track_id}.mp3        # config.js 규약 파일명
      → rclone copy → r2:{bucket}/               # 공개 URL로 재생

사전 준비 (사용자가 직접 — 인증은 대신 할 수 없음):
    1) rclone 원격 2개 설정
         rclone config   → name=drive, type=drive          (Google 계정 OAuth)
         rclone config   → name=r2,    type=s3, provider=Cloudflare
                           (R2 대시보드 > Manage API Tokens 에서 Access Key ID/Secret 발급,
                            endpoint = https://<account_id>.r2.cloudflarestorage.com)
    2) 확인:  rclone lsd drive:   /   rclone lsd r2:

사용법:
    python scripts/fetch_demo_audio.py --bucket <R2버킷명> --dry-run
    python scripts/fetch_demo_audio.py --bucket <R2버킷명>
    python scripts/fetch_demo_audio.py --bucket <R2버킷명> --only YLD-20260601-0004
    python scripts/fetch_demo_audio.py --bucket <R2버킷명> --verify-only
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = PROJECT_ROOT / "data" / "demo_tracks.json"
WORK_DIR = PROJECT_ROOT / "cache" / "audio_build"
RAW_DIR = WORK_DIR / "raw"
OUT_DIR = WORK_DIR / "mp3"

# yieldus_player_founder/tools/ 에 이미 들어 있는 실행파일들을 우선 사용한다.
TOOLS_DIR = PROJECT_ROOT.parent / "yieldus_player_founder" / "tools"


def find_exe(name: str) -> str | None:
    local = TOOLS_DIR / f"{name}.exe"
    if local.exists():
        return str(local)
    return shutil.which(name)


def run(cmd: list[str], *, quiet: bool = False) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        return 127, str(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    if not quiet and proc.returncode != 0:
        print(f"    실패({proc.returncode}): {out.strip()[:300]}")
    return proc.returncode, out


def check_prereqs(rclone: str | None, ffmpeg: str | None) -> list[str]:
    problems = []
    if not rclone:
        problems.append("rclone을 찾을 수 없습니다 (tools/rclone.exe 또는 PATH).")
    if not ffmpeg:
        problems.append("ffmpeg을 찾을 수 없습니다 (tools/ffmpeg.exe 또는 PATH).")
    if rclone:
        code, out = run([rclone, "listremotes"], quiet=True)
        # listremotes는 "name:" 형태만 원격이다. NOTICE/ERROR 로그 줄을 걸러낸다.
        remotes = {
            line.strip().rstrip(":")
            for line in out.splitlines()
            if line.strip().endswith(":") and " " not in line.strip()
        }
        for needed in ("drive", "r2"):
            if needed not in remotes:
                problems.append(
                    f"rclone 원격 '{needed}:' 가 없습니다. `rclone config`로 먼저 설정하세요. "
                    f"(현재: {sorted(remotes) or '없음'})"
                )
    return problems


def fetch_one(rclone: str, ffmpeg: str, track: dict, bucket: str, dry: bool) -> str:
    """반환값: 'ok' | 'skip' | 'fail:<이유>'"""
    tid = track["track_id"]
    fid = track.get("drive_file_id")
    if not fid:
        return "fail:drive_file_id 없음"

    mp3 = OUT_DIR / f"{tid}.mp3"
    if mp3.exists():
        print(f"    변환본 있음, 재사용: {mp3.name}")
    else:
        stage = RAW_DIR / tid
        if dry:
            print(f"    [dry] rclone backend copyid drive: {fid} {stage}")
            print(f"    [dry] ffmpeg → {mp3.name}")
        else:
            stage.mkdir(parents=True, exist_ok=True)
            # copyid는 파일 ID로 받아 디렉터리에 원본 파일명으로 저장한다.
            code, out = run([rclone, "backend", "copyid", "drive:", fid, str(stage) + "/"])
            if code != 0:
                return f"fail:drive 다운로드 실패 ({out.strip()[:120]})"
            files = [p for p in stage.iterdir() if p.is_file()]
            if not files:
                return "fail:다운로드된 파일이 없음"
            src = max(files, key=lambda p: p.stat().st_size)
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            code, out = run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", "128k",
                str(mp3),
            ])
            if code != 0 or not mp3.exists():
                return f"fail:ffmpeg 변환 실패 ({out.strip()[:120]})"
            print(f"    변환 완료: {src.name} → {mp3.name} ({mp3.stat().st_size//1024}KB)")

    if dry:
        print(f"    [dry] rclone copyto {mp3.name} r2:{bucket}/{tid}.mp3")
        return "ok"

    code, out = run([rclone, "copyto", str(mp3), f"r2:{bucket}/{tid}.mp3"])
    if code != 0:
        return f"fail:R2 업로드 실패 ({out.strip()[:120]})"
    return "ok"


def verify(audio_base: str, tracks: list[dict]) -> None:
    try:
        import httpx
    except ImportError:
        print("httpx가 없어 검증을 건너뜁니다.")
        return
    print("\nR2 공개 URL 검증:")
    ok = 0
    for t in tracks:
        url = f"{audio_base.rstrip('/')}/{t['track_id']}.mp3"
        try:
            r = httpx.head(url, timeout=15, follow_redirects=True)
            size = r.headers.get("content-length")
            if r.status_code == 200:
                ok += 1
                print(f"  [OK  ] {t['track_id']}  {int(size)//1024 if size else '?'}KB")
            else:
                print(f"  [{r.status_code}] {t['track_id']}")
        except Exception as exc:
            print(f"  [ERR ] {t['track_id']} {exc}")
    print(f"\n재생 가능: {ok}/{len(tracks)}곡")
    if ok < len(tracks):
        print("404가 나오면 R2 버킷의 Public access(r2.dev) 와 CORS(GET, Origin 허용)를 확인하세요.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", help="R2 버킷명 (업로드 시 필수)")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--only", action="append", help="특정 track_id만 (반복 가능)")
    ap.add_argument("--limit", type=int, help="앞에서 N곡만")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify-only", action="store_true", help="업로드 없이 R2 URL만 확인")
    ap.add_argument("--include-rejected", action="store_true",
                    help="review=reject 로 표시된 곡도 포함 (기본 제외)")
    args = ap.parse_args()

    if not args.manifest.exists():
        print(f"매니페스트가 없습니다: {args.manifest}")
        print("먼저 실행: python scripts/curate_demo_tracks.py")
        return 2

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    tracks = payload.get("tracks") or []
    audio_base = payload.get("audio_base") or ""

    if not args.include_rejected:
        before = len(tracks)
        tracks = [t for t in tracks if t.get("review") != "reject"]
        if before != len(tracks):
            print(f"review=reject 제외: {before - len(tracks)}곡")

    if args.only:
        wanted = set(args.only)
        tracks = [t for t in tracks if t["track_id"] in wanted]
    if args.limit:
        tracks = tracks[: args.limit]

    if not tracks:
        print("대상 곡이 없습니다.")
        return 1

    if args.verify_only:
        verify(audio_base, tracks)
        return 0

    if not args.bucket:
        print("--bucket 이 필요합니다 (R2 버킷명). 확인: rclone lsd r2:")
        return 2

    rclone, ffmpeg = find_exe("rclone"), find_exe("ffmpeg")
    problems = check_prereqs(rclone, ffmpeg)
    if problems:
        print("사전 준비가 필요합니다:")
        for p in problems:
            print(f"  - {p}")
        print("\n설정 방법은 이 파일 상단 주석을 참고하세요.")
        return 2

    print(f"rclone: {rclone}\nffmpeg: {ffmpeg}")
    print(f"대상 {len(tracks)}곡 → r2:{args.bucket}/{{track_id}}.mp3"
          + ("  [DRY RUN]" if args.dry_run else ""))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results: dict[str, str] = {}
    for i, t in enumerate(tracks, 1):
        print(f"\n[{i}/{len(tracks)}] {t['track_id']} — {t.get('title') or ''}")
        results[t["track_id"]] = fetch_one(rclone, ffmpeg, t, args.bucket, args.dry_run)

    ok = [k for k, v in results.items() if v == "ok"]
    fail = {k: v for k, v in results.items() if v.startswith("fail")}
    print("\n" + "=" * 66)
    print(f"성공 {len(ok)} / 실패 {len(fail)} / 전체 {len(tracks)}")
    if fail:
        print("\n실패 목록:")
        for k, v in fail.items():
            print(f"  {k}: {v[5:]}")
    print("=" * 66)

    if ok and not args.dry_run:
        verify(audio_base, [t for t in tracks if t["track_id"] in set(ok)])
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
