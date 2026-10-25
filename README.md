# dedupe_photos

A small Python script that finds duplicate photos (and videos) in a deeply nested folder tree and moves the extra copies out of the way, without deleting anything.

It is built for the "years of photos merged from several computers" situation: duplicates can live in folders with completely different names, and files may even have been renamed. Duplicates are detected by **file content** (SHA-256), not by name or location.

## Features

- Detects byte-identical files regardless of file name or folder name
- Never deletes: duplicates are **moved** to a separate folder, keeping their original names and relative folder structure
- Dry-run by default, so you can review before anything changes
- CSV report showing which copy was kept and which were moved
- Original names and folder grouping of the kept files are left untouched
- Fast: files are compared by size first, then a partial hash, and only then a full hash
- No external dependencies

## Requirements

- Python 3.10 or newer

## Usage

```
python dedupe_photos.py <photos_folder> [options]
```

### 1. Dry run (default, changes nothing)

```
python dedupe_photos.py "D:\Photos"
```

Prints the number of duplicate groups, extra copies and the space that would be freed, and writes `dedupe_report.csv`.

### 2. Move the duplicates

```
python dedupe_photos.py "D:\Photos" --apply
```

Duplicates are moved to `D:\Photos_duplicates`, preserving their relative paths.

### Options

| Option | Description |
|---|---|
| `--apply` | Actually move the duplicates. Without it, the script only reports. |
| `--dup-dir PATH` | Folder to move duplicates into (default: `<photos_folder>_duplicates`, next to the original). |
| `--remove-empty` | After moving, delete folders left empty in the photos folder. |
| `--all-files` | Check every file type, not just photos and videos. |
| `--report NAME` | Name of the CSV report (default: `dedupe_report.csv`). |

## Which copy is kept?

For each group of identical files, the script keeps one using these rules, in order:

1. The file located in the folder containing the most media files (most likely a real album)
2. A file whose name does not look like a copy (`(1)`, `copy`, `copies`, ...)
3. The shorter file name
4. The oldest modification date
5. Alphabetical path, as a final tie-breaker

All other copies in the group are moved to the duplicates folder.

## Supported file types

Photos: `jpg`, `jpeg`, `png`, `gif`, `bmp`, `tif`, `tiff`, `webp`, `heic`, `heif`, and RAW formats (`raw`, `cr2`, `cr3`, `nef`, `arw`, `dng`, `orf`, `rw2`).

Videos: `mp4`, `mov`, `avi`, `mkv`, `3gp`, `m4v`.

Use `--all-files` to include everything else.

## Report format

`dedupe_report.csv` (semicolon-separated, UTF-8 with BOM so it opens correctly in Excel):

| Column | Meaning |
|---|---|
| KEPT | Path of the file that stays |
| DUPLICATE | Path of the file that is (or would be) moved |
| SIZE (bytes) | Size of the duplicate |

## Limitations

- Only **exact** duplicates are found. Resized, re-compressed, cropped or edited versions of a photo are different files and are not detected.
- If a file with the same relative path already exists in the duplicates folder, the moved file gets a `__dup1`, `__dup2`, ... suffix instead of overwriting anything.
- Symbolic links are skipped.

## Recommended workflow

1. Back up the photos folder.
2. Run a dry run and skim `dedupe_report.csv`.
3. Run with `--apply`.
4. Browse your library and the `_duplicates` folder to confirm everything looks right.
5. Delete the `_duplicates` folder once you are satisfied.