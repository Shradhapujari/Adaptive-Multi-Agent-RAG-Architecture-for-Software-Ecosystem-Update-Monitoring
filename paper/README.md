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

18 remain, down from 180. They come from seven entries, and every one is a
property of where the work was published rather than a gap in the record:

| Entries | Missing | Why |
|---|---|---|
| `asai2024selfrag`, `hong2024metagpt`, `jimenez2024swebench` | publisher, address, pages | ICLR proceedings are OpenReview: no publisher and no page numbers exist. |
| `thakur2021beir`, `zhuge2024` | pages (and address for PMLR) | NeurIPS Datasets & Benchmarks and ICML papers are not paginated. |
| `izacard2022contriever` | volume, number, pages | TMLR is a rolling journal; it issues neither. |
| `liu2026agentsurvey`, `mamun2026blagent` | volume, number, pages | Forthcoming in TOSEM, no issue assigned yet. Fill these in once they appear. |

Do not "fix" these by inventing values. The only one that will ever resolve is
the last row, when those two papers are assigned an issue.

### How the rest were fixed

The publisher and address of a co-sponsored SE venue cannot be guessed --
it alternates. Verified against Crossref by title and year, ICSE alone runs
IEEE in 2013, ACM in 2014, IEEE in 2015, ACM in 2018, IEEE in 2023, ACM in
2024, IEEE in 2025. All 19 were resolved that way, each to an exact title
match with a DOI; the DOIs are in the lookup log if they are ever wanted in
the entries themselves.

Earlier passes fixed the mechanical cases: fifteen arXiv preprints typed as
`@article` with a `journal` field (a preprint has no volume, number or pages,
so each raised three warnings), three repository entries with no year, and 45
proceedings whose venue names its own publisher.

## Where the numbers come from

Every figure in the results tables is traceable to a run directory:
[`../results/PROVENANCE.md`](../results/PROVENANCE.md) maps each table to the
run that produced it, and marks the runs that superseded earlier ones and why.
