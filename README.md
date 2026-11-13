# Archive of `ICPC27-E02-counterfactual-explanations`

- Created: 2026-11-10T19:16:31+07:00
- Source folder: `/Users/xuanbachle/Workstation/ICPC-NIER/ICPC-ERA/drive-export/ICPC27-E02-counterfactual-explanations`
- Kept locally (not archived): nothing
- Format: zip (deflate), archives larger than 4.8 GB split into byte parts
- Every archive was tested with `unzip -t`; SHA-256 values below were taken before upload.

## Notes

Public archive (same content as the private GitHub repo) of an ICPC 2027 ERA paper + artifact. Share: anyone with the link can view.

## Archives

| # | Archive file(s) | Original paths | Files | Original size | Archive size |
|---|---|---|---|---|---|
| 01 | `01_root__small-items.zip` | `.gitignore`<br>`STATUS.md`<br>`artifact`<br>`manuscript`<br>`others`<br>`review.md` | 3,421 | 12.2 MB | 4.6 MB |

## Checksums (SHA-256)

```
2c130ca17c3c3d487a22f03becf79f716b339db8b2778465f82a80c79172a760  01_root__small-items.zip
```

## Restore

Single archive: `unzip <label>.zip -d <restore-dir>` (paths are relative to the source folder).

Split archive: join the parts in order, check the hash, then unzip:

```sh
cat <label>.zip.part* > <label>.zip
shasum -a 256 <label>.zip   # compare with the value above
unzip <label>.zip -d <restore-dir>
```

To rebuild the original folder, unzip every archive into the same directory and put the kept paths back.
`MANIFEST.tsv.gz` lists every archived file (archive label, relative path, size in bytes).
