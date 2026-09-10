# Building the paper

```bash
cd paper
mkdir -p /tmp/build && tectonic tosem_amara.tex --outdir /tmp/build
```

`--outdir` must already exist; tectonic will not create it.

`tectonic` fetches what it needs on first run; no TeX install required. Any
LaTeX toolchain works, but the sequence has to be
`pdflatex → bibtex → pdflatex → pdflatex` — one pass leaves the citations
unresolved.

Last verified 2026-09-10: 0 errors, 47 pages, no unresolved references.

## Editing the bibliography: read this first

**`tosem_amara.bbl` is committed, and LaTeX typesets it directly. Editing
`references.bib` changes nothing until the `.bbl` is regenerated.**

This fails silently. The bibliography still builds, the citations still
resolve, and the output is simply the old one. It cost two full rebuilds to
notice, both showing a warning count that had not moved by a single line after
substantive edits.

To change a reference:

```bash
cd paper
mkdir -p /tmp/build
mv tosem_amara.bbl /tmp/                       # force bibtex to run
tectonic tosem_amara.tex --outdir /tmp/build --keep-intermediates
cp /tmp/build/tosem_amara.bbl tosem_amara.bbl  # commit the result
```

Commit the regenerated `.bbl` alongside the `.bib` change. The repository
tracks it because a submission wants a self-contained build; that convenience
is exactly what makes the trap possible.

## Which files are live

| File | Status |
|---|---|
| `tosem_amara.tex` | The paper. Self-contained — no `\input`. |
| `references.bib` | The **only** bibliography source; `\bibliography{references}` cites it alone. |
| `tosem_amara.bbl` | Generated from the above. Typeset directly. See the warning. |
| `ACM-Reference-Format.bst` | ACM's style file. |

Everything tracked in `paper/` is live. Five uncited `.bib` files and six
orphaned `frag_*.tex` drafts used to sit here and were removed in
`docs/paper-dead-files`: they were a second way to spend an afternoon on an
edit that could not reach the output. Only one entry in any of them was worth
keeping (Self-RAG's arXiv id, now folded in), and several actively disagreed
with `references.bib` on authors, venue and arXiv id -- the copies here were
older and wrong, not merely redundant. Recover them from git history if ever
needed, but check them against `references.bib` before trusting a field.

## Outstanding BibTeX warnings

56 remain, down from 180. Each needs a per-entry lookup and an author's
judgement about what to assert, so none should be closed by a script:

- **22 empty publisher, 23 empty address.** Nearly all are `{IEEE/ACM}`
  co-sponsored SE venues — ICSE, ASE, ESEM — where the publisher of record
  alternates by year between IEEE and ACM. The three ICLR papers have no
  publisher at all; ICLR proceedings are OpenReview.
- **8 missing page numbers.** ICLR, NeurIPS and ICML papers do not have them.
- **3 missing volume or number.** TMLR is a rolling journal without volumes;
  the two TOSEM entries are forthcoming and have no issue assigned.

The warnings that *were* mechanical are already fixed: fifteen arXiv preprints
typed as `@article` with a `journal` field (a preprint has no volume, number or
pages, so each raised three warnings), and three repository entries with no
year, dated from the GitHub API rather than from their citation keys — note
that `flashrag2025repo` was in fact created in March 2024.

## Where the numbers come from

Every figure in the results tables is traceable to a run directory:
[`../results/PROVENANCE.md`](../results/PROVENANCE.md) maps each table to the
run that produced it, and marks the runs that superseded earlier ones and why.
