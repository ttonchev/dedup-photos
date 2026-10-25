#!/usr/bin/env python3
"""
Remove duplicate photos (by content) from nested folders.

- Compares files by SHA-256, not by name or folder.
- Nothing is deleted: duplicates are MOVED to a separate folder,
    preserving the folder structure and original filenames.
- Runs in dry-run mode by default. Add --apply to move files for real.
- Any folder or file that cannot be read is REPORTED (stderr, summary and
    dedupe_errors.csv). If the scan was incomplete, --apply is refused unless
    --allow-incomplete is given. Exit code is non-zero when errors occurred.

Examples:
    python dedupe_photos.py "D:\\Photos"                 # only shows what it would do
    python dedupe_photos.py "D:\\Photos" --apply         # moves the duplicates
    python dedupe_photos.py "D:\\Photos" --apply --remove-empty
    python dedupe_photos.py "D:\\Photos" --dup-dir "E:\\Duplicates" --apply
"""
import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

MEDIA_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".heic", ".heif", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf",
    ".rw2", ".mp4", ".mov", ".avi", ".mkv", ".3gp", ".m4v",
}

COPY_PATTERN = re.compile(r"(\(\d+\)|\bcopy\b|\bcopies\b|_copy|- copy)", re.IGNORECASE)


def record_error(errors: list, stage: str, path, exc: Exception) -> None:
    """Remember an error and print it immediately."""
    reason = getattr(exc, "strerror", None) or str(exc)
    errors.append((stage, str(path), reason))
    print(f"\n! [{stage}] {path}: {reason}", file=sys.stderr)


def write_error_report(errors: list, report_path: str) -> None:
    if not errors:
        # Do not leave a stale error report from a previous run.
        try:
            os.remove(report_path)
        except OSError:
            pass
        return
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["STAGE", "PATH", "REASON"])
        w.writerows(errors)


def sha256(path: Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        if limit:
            h.update(f.read(limit))
        else:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def scan(root: Path, skip_dir: Path, all_files: bool, errors: list):
    files = []

    def on_walk_error(exc: OSError):
        # Called by os.walk when a directory cannot be listed (permissions, I/O error...).
        record_error(errors, "scan: directory not readable", exc.filename or root, exc)

    for dirpath, dirnames, filenames in os.walk(root, onerror=on_walk_error):
        current = Path(dirpath)
        # Skip the duplicates folder if it is inside root.
        dirnames[:] = [d for d in dirnames if (current / d) != skip_dir]
        for name in filenames:
            p = current / name
            if not all_files and p.suffix.lower() not in MEDIA_EXT:
                continue
            try:
                if p.is_symlink():
                    continue
            except OSError as e:
                record_error(errors, "scan: file check failed", p, e)
                continue
            files.append(p)
    return files


def find_duplicates(files, errors: list):
    # 1) By size.
    by_size = defaultdict(list)
    for p in files:
        try:
            by_size[p.stat().st_size].append(p)
        except OSError as e:
            record_error(errors, "stat", p, e)

    candidates = [g for size, g in by_size.items() if len(g) > 1 and size > 0]

    # 2) Hash the first 64 KB, then compute the full hash.
    groups = []
    total = sum(len(g) for g in candidates)
    done = 0
    for g in candidates:
        by_quick = defaultdict(list)
        for p in g:
            try:
                by_quick[sha256(p, 65536)].append(p)
            except OSError as e:
                record_error(errors, "hash", p, e)
        for qg in by_quick.values():
            if len(qg) < 2:
                continue
            by_full = defaultdict(list)
            for p in qg:
                try:
                    by_full[sha256(p)].append(p)
                except OSError as e:
                    record_error(errors, "hash", p, e)
            groups.extend(fg for fg in by_full.values() if len(fg) > 1)
        done += len(g)
        print(f"\r  candidates checked: {done}/{total}", end="", file=sys.stderr)
    print(file=sys.stderr)
    return groups


def choose_keeper(group, folder_counts):
    def key(p: Path):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = float("inf")
        return (
            -folder_counts[p.parent],              # A folder with more photos is more likely to be a real album.
            1 if COPY_PATTERN.search(p.stem) else 0,  # Avoid names like "(1)", "copy", and "copies".
            len(p.name),
            mtime,                                  # The oldest file.
            str(p).lower(),
        )
    return min(group, key=key)


def unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 1
    while True:
        cand = dest.with_name(f"{stem}__dup{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1


def remove_empty_dirs(root: Path, errors: list):
    removed = 0

    def on_walk_error(exc: OSError):
        record_error(errors, "remove-empty: directory not readable", exc.filename or root, exc)

    for dirpath, _, _ in os.walk(root, topdown=False, onerror=on_walk_error):
        p = Path(dirpath)
        if p == root:
            continue
        try:
            if not any(p.iterdir()):
                p.rmdir()
                removed += 1
        except OSError as e:
            record_error(errors, "remove-empty", p, e)
    return removed


def main():
    ap = argparse.ArgumentParser(description="Find and move duplicate photos.")
    ap.add_argument("root", help="Root folder containing photos")
    ap.add_argument("--dup-dir", help="Where to move duplicates (default: <root>_duplicates)")
    ap.add_argument("--apply", action="store_true", help="Actually move files (otherwise, run in dry-run mode)")
    ap.add_argument("--all-files", action="store_true", help="Check all files, not just photos and videos")
    ap.add_argument("--remove-empty", action="store_true", help="Remove folders left empty after moving files")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="Allow --apply even if some folders/files could not be read")
    ap.add_argument("--report", default="dedupe_report.csv", help="Name of the CSV report")
    ap.add_argument("--error-report", default="dedupe_errors.csv", help="Name of the CSV error report")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"Folder does not exist: {root}")

    dup_dir = Path(args.dup_dir).expanduser().resolve() if args.dup_dir else root.with_name(root.name + "_duplicates")

    errors: list = []

    print(f"Scanning: {root}")
    files = scan(root, dup_dir, args.all_files, errors)
    print(f"  files found: {len(files)}")
    if errors:
        print(f"  WARNING: {len(errors)} problem(s) during scan - the file list may be incomplete.",
              file=sys.stderr)

    folder_counts = defaultdict(int)
    for p in files:
        folder_counts[p.parent] += 1

    print("Finding duplicates...")
    groups = find_duplicates(files, errors)

    rows = []
    to_move = []
    saved = 0
    for g in groups:
        keeper = choose_keeper(g, folder_counts)
        for p in g:
            if p == keeper:
                continue
            try:
                size = p.stat().st_size
            except OSError as e:
                record_error(errors, "stat", p, e)
                continue
            saved += size
            to_move.append(p)
            rows.append([str(keeper), str(p), size])

    print(f"\nDuplicate groups: {len(groups)}")
    print(f"Extra copies:     {len(to_move)}")
    print(f"Space recovered:  {saved / (1024 ** 2):.1f} MB")

    with open(args.report, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["KEEPER", "DUPLICATE (moved)", "SIZE (bytes)"])
        w.writerows(rows)
    print(f"Report: {os.path.abspath(args.report)}")

    # Refuse to modify anything based on an incomplete scan.
    if errors and args.apply and not args.allow_incomplete:
        write_error_report(errors, args.error_report)
        print(f"\nABORTED: {len(errors)} folder(s)/file(s) could not be read, so the scan is incomplete.",
              file=sys.stderr)
        print(f"Details: {os.path.abspath(args.error_report)}", file=sys.stderr)
        print("Fix the permissions and re-run, or use --allow-incomplete to move anyway.", file=sys.stderr)
        sys.exit(2)

    if not args.apply:
        write_error_report(errors, args.error_report)
        if errors:
            print(f"\nDry-run finished WITH {len(errors)} ERROR(S): the results above are incomplete.",
                  file=sys.stderr)
            print(f"Details: {os.path.abspath(args.error_report)}", file=sys.stderr)
            sys.exit(2)
        print("\nDry-run mode - nothing was changed. Review the report and run with --apply.")
        return

    moved = 0
    for p in to_move:
        dest = unique_dest(dup_dir / p.relative_to(root))
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))
            moved += 1
        except OSError as e:
            record_error(errors, "move", p, e)

    print(f"\nFiles moved: {moved} -> {dup_dir}")

    if args.remove_empty:
        n = remove_empty_dirs(root, errors)
        print(f"Empty folders removed: {n}")

    write_error_report(errors, args.error_report)
    if errors:
        print(f"\nFinished WITH {len(errors)} ERROR(S). Details: {os.path.abspath(args.error_report)}",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()