"""Where every number in the repository comes from (2026-11-17): the provenance ledger and its check.

Every tracked file has a CLASS in docs/FIGURE_PROVENANCE.json (first matching rule wins; a file no rule matches FAILS):

  current     a file that states the present (CLAUDE.md, STATE.md, runbooks, the deploy sheet). Every figure in it must be
              DATED (an ISO date, YYYY-MM or YYYY-MM-DD, on its line, on the first line of its paragraph, or in a heading above
              it), CHECKED (a `checked` entry of the ledger names the test that reads it against live or against its source,
              and the entry's pattern still matches the line), or marked UNTRACEABLE in place, in the form
              `UNTRACEABLE (settle: <what would settle it>)`. Anything else FAILS, named by file and line.
  code        source code. The same rule, applied to comments, docstrings and prose strings (on-screen text, messages);
              a figure that is also a literal in the file's own code is a DEFINITION of that code and passes.
  record      a dated record: a report of a run, an experiment, a rehearsal, an audit. A Markdown record must carry the
              label `Dated record (<ISO date>` in its first 8 lines; a non-Markdown record is labelled by its rule's `dated`
              field (date and what produced it), because a CSV or JSON cannot carry a banner without breaking its readers.
  generated   written by a script. The rule names the generator and the verifier; the verifier must be run by
              scripts/check.sh (or be null with a reason). Its figures trace to that script and the run it read.
  data        data, not claims (the data folders, configuration maps, assets, lock files). Its figures trace to the commit that
              set them.
  fixture     tests. Inputs and expectations of synthetic cases. A test line that says its figure was read from live must
              carry the date it was read.
  manuscript  the chapter drafts and edit lists (out of scope by Kelvin's brief of 2026-11-17: knowingly stale). Counted,
              not checked.

What counts as a figure: a number with a decimal point, a thousands comma or a percent sign, or an integer of 10 or more,
that is not a date, a year, a time, a version, a hash, a migration number, a line reference, a path, or an identifier
(rule, step, table, figure, section, DEC-, lp_run, run, row/item/issue ids, ports, HTTP statuses, CSS sizes). Integers
under 10 are not tracked: in prose they are mostly structure ("3 windows", "rule 2"), and the cost of tracking them is a
ledger nobody reads. That is a stated limit of this check, not a claim that they are all correct.

Known weakness, stated: "dated" is mechanical. A present-tense figure on a line that also carries a date passes. The check
proves that every figure carries a date, a live test or an UNTRACEABLE marker; it does not prove that a dated figure is
still true (a dated figure is a record by definition).

    python -m scripts.figure_provenance --verify              # the check (scripts/check.sh --fast); no database
    python -m scripts.figure_provenance --inventory [PATH]    # every figure, one row each, to PATH (default: local/, git-ignored)
    python -m scripts.figure_provenance --residue             # the figures in current/code files that are none of the above
"""
from __future__ import annotations

import argparse
import ast
import csv
import fnmatch
import importlib
import io
import json
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "docs" / "FIGURE_PROVENANCE.json"
CHECK_SH = REPO / "scripts" / "check.sh"
CLASSES = ("current", "code", "record", "generated", "data", "fixture", "manuscript")
TEXT_EXT = {".md", ".txt", ".yaml", ".yml", ".sh", ".toml", ".html", ".py", ".js", ".jsx", ".sql", ".css", ".json", ".csv"}

ISO = re.compile(r"\b20\d\d-(0[1-9]|1[0-2])(-([0-2]\d|3[01]))?\b")
BANNER = re.compile(r"Dated record \(([^)]*\b20\d\d-\d\d(-\d\d)?\b)", re.I)
# a current file whose figures all describe one fixed thing (a seed backup, a spec) dates them once, in its head
FIGURES_AS_OF = re.compile(r"Figures as of (20\d\d-\d\d(-\d\d)?)\b")
HTTP_CODES = {"200", "201", "202", "204", "301", "302", "304", "400", "401", "403", "404", "405", "409", "410", "413", "415", "422",
              "429", "500", "502", "503", "504"}
HTTP_CONTEXT = re.compile(r"\b(HTTP|status|answer|answers|answered|returns?|refus\w*|route|routes|error|errors|response|GET|POST|"
                          r"PUT|DELETE|PATCH|plain|code|raises?|Not Found|Conflict|Unprocessable|Unauthorized|Forbidden)\b"
                          r"|\b\d{3}\s+`?[a-z]+_[a-z_]+", re.I)
PORTS = {"8000", "5173", "5432", "6543", "55432", "4173", "3000"}
PORT_CONTEXT = re.compile(r"port|127\.0\.0\.1|localhost|uvicorn|vite|direct URL|pooler", re.I)
UNTRACEABLE = re.compile(r"UNTRACEABLE \(settle: [^)]{8,}\)")
NUM = re.compile(r"(?<![\w.#/@=<>:$-])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)(\s?%)?(?![\w/.]|\.\d)")
# a number right after one of these words is an identifier, not a measurement
ID_WORDS = re.compile(
    r"(?:\b(?:rule|rules|step|steps|table|tables|figure|figures|fig|section|sections|chapter|chapters|line|lines|item|items|"
    r"issue|issues|phase|phases|port|pr|dec|migration|migrations|lp_run|run|runs|run_id|run_key|lp|version|python|http|"
    r"status|page|gate|tier|round|row|block|batch|commit|node|react|vite|cycle|week|day|level|appendix|criterion|test|"
    r"question|q|case|option|stage|layer|fold|shard|attempt|bin|model|scheme|candidate|check|hop|part|slice|wave|"
    r"utf|iso|sha|md5|base|x|postgresql|postgres|pg|node|npm|errno|chrome|windows|es|rfc|u\+|wcag|ijf|jors)\s*[-#_ ]?\s*|[§#]\s*)$", re.I)
UNIT_AFTER = re.compile(r"^\s*(px|rem|em|vh|vw|fr|deg|ms\b(?=\s*[,;)]?\s*(ease|linear|cubic))|dpi\b)", re.I)
STRIP = [
    re.compile(r"https?://\S+"),                                                    # URLs first: later rules would cut them up
    re.compile(r"\b\d{1,3}(?:\\?\.\d{1,3}){3}\b"),                                  # IPv4 addresses (also written as a regex)
    re.compile(r"\b20\d\d-\d\d-\d\d(?:[T ]\d\d:\d\d(?::\d\d)?(?:\.\d+)?Z?)?\b"),    # dates and timestamps
    re.compile(r"\b20\d\d-\d\d\b"),                                                 # months
    re.compile(r"\b\d\d:\d\d(?::\d\d)?\b"),                                         # times
    re.compile(r"\b[0-9a-f]{7,40}\b"),                                              # hashes
    re.compile(r"[\w./\\-]+\.(?:py|md|jsx?|json|sql|csv|sh|ya?ml|txt|html|css|png|svg|pkl|xlsx?|parquet|log|gz)"
               r"(?::\d+(?:-:?\d+)?)?(?:#L\d+(?:-L\d+)?)?"),                       # paths and line references
    re.compile(r"(?<![\w])[:#]L?\d+(?:-L?\d+)?\b"),                                 # :123, #L12-L40
    re.compile(r"\bDEC-\d+\b|\b[A-Z]{1,3}\d{1,3}[a-z]?\b"),                         # DEC-41, A12, G14, P5b, H2, C31
    re.compile(r"\b0\d{3}\b"),                                                      # migration numbers
    re.compile(r"\b(?:NUMERIC|DECIMAL|VARCHAR|CHAR|numeric|decimal|varchar)\(\d+(?:,\s*\d+)?\)"),  # SQL type sizes
    re.compile(r"\b(?:RA|R\.A\.|Republic Act)\s*(?:No\.\s*)?\d+"),                  # statutes
    re.compile(r"\bv?\d+\.\d+\.\d+(?:[.-]\w+)*\b"),                                 # versions, section numbers 4.2.18
    re.compile(r"\b(?:19|20)\d\d\b"),                                               # years
    re.compile(r"\b\d+(?:st|nd|rd|th)\b"),                                          # ordinals
    re.compile(r"\b[\w-]*\d+[A-Za-z_]+[\w-]*\b|\b[A-Za-z_][\w-]*\d+[\w-]*\b"),        # identifiers holding digits
    re.compile(r"https?://\S+"),
    re.compile(r"\b(?:rgba?|hsla?|translate[XYZ]?|scale|rotate|cubic-bezier|calc|var|minmax|repeat)\([^)]*\)"),  # CSS
    re.compile(r"\b\d+(?:\.\d+)?(?:px|rem|em|vh|vw|ms|fr|deg|kB|KB|MB|dpi)\b"),     # sizes and durations with a unit
    re.compile(r"\{[^{}]*\}"),                                                      # format fields in code strings
]


@dataclass(frozen=True)
class Figure:
    file: str
    line: int
    figure: str
    text: str
    status: str          # dated | checked | definition | untraceable | residue | <class> for whole-file classes


def figures_in(line: str, code: bool = False) -> list[str]:
    """The figures a line states. `code`: the line is a comment or string of source code, where a bare HTTP status
    (raising 413, a 403, 202 when held) is always the status, never a measurement."""
    s = line
    for rx in STRIP:
        s = rx.sub(lambda m: " " * len(m.group(0)), s)
    out = []
    for m in NUM.finditer(s):
        num, pct = m.group(1), (m.group(2) or "").strip()
        before, after = s[:m.start()], s[m.end():]
        if ID_WORDS.search(before[-24:]) or UNIT_AFTER.match(after):
            continue
        rng = re.search(r"(\d+)\s*[–-]\s*$", before)        # the second end of a range of ids: "Steps 10–11"
        if rng and ID_WORDS.search(before[:rng.start()][-24:]):
            continue
        if not pct and num in HTTP_CODES and (code or HTTP_CONTEXT.search(line)):
            continue
        if not pct and num in PORTS and PORT_CONTEXT.search(line):
            continue
        v = float(num.replace(",", ""))
        if pct or "." in num or "," in num or v >= 10:
            out.append(num + pct)
    return out


# ---------------------------------------------------------------- the text a file states, line by line
# Each extractor returns (lineno, text, block) triples; a block is a paragraph, a table row, a comment block or a docstring
# paragraph. A figure is dated when any line of its block, or a heading above it (Markdown), carries an ISO date.
def _dated(items, head_dated=None):
    blocks: dict[object, bool] = {}
    for i, ln, b in items:
        blocks[b] = blocks.get(b, False) or bool(ISO.search(ln))
    return [(i, ln, blocks[b] or bool(head_dated and head_dated.get(i))) for i, ln, b in items]


def _md_lines(text: str):
    items, head_dated = [], {}
    heads: list[tuple[int, bool]] = []
    block, in_para = 0, False
    for i, line in enumerate(text.splitlines(), 1):
        st = line.strip()
        h = re.match(r"^(#{1,6})\s", line)
        if h:
            lvl = len(h.group(1))
            heads = [x for x in heads if x[0] < lvl] + [(lvl, bool(ISO.search(line)))]
            block += 1
            in_para = False
        elif not st:
            in_para = False
            continue
        elif st.startswith("|") or not in_para or (not line[:1].isspace() and _starts_entry(line)):
            block += 1
            in_para = True
        head_dated[i] = any(d for _, d in heads)
        items.append((i, line, block))
    return _dated(items, head_dated)


def _starts_entry(line: str) -> bool:
    """An unindented line that begins a new entry (STATE.md's entries, list items) rather than continuing a wrapped one."""
    return bool(re.match(r"^([A-Z][A-Z0-9 ,'()/+-]{3,}[(.:]|[-*] |\d+\. |> |[A-Za-z_]+:)", line))


def _py_lines(text: str):
    """Comments, docstrings and prose strings of a Python file, with the code's own literals for the definition rule."""
    items, code_nums = [], set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return _dated([(i, ln, i) for i, ln in enumerate(text.splitlines(), 1)]), code_nums
    doc_starts = set()
    try:
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                b = node.body[0]
                if isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant) and isinstance(b.value.value, str):
                    doc_starts.add(b.lineno)
    except SyntaxError:
        pass
    prev_comment, cblock = -10, None
    prev_string_end, sblock = -10, None      # adjacent string tokens ("..." "...") are one sentence: one block
    for t in toks:
        if t.type == tokenize.NUMBER:
            code_nums.add(_norm(t.string))
        elif t.type == tokenize.COMMENT:
            ln = t.start[0]
            if ln != prev_comment + 1:
                cblock = ("c", ln)
            prev_comment = ln
            items.append((ln, t.string, cblock))
        elif t.type == tokenize.STRING:
            s0, body = t.start[0], t.string
            prose = s0 in doc_starts or len(re.findall(r"[A-Za-z]{3,}", body)) >= 3
            # markup and script held in a Python string (HTML e-mails, the review page's JavaScript) is code, not text
            markup = s0 not in doc_starts and bool(re.search(r"<[a-z/][^>]*>|\bconst \w+ =|=>|\$\{|style=|;\s*$", body, re.M))
            if not prose or markup or re.match(r"^[rbuf]*['\"]{1,3}\s*(SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|ALTER|FROM)\b", body, re.I):
                for n in figures_in(body):
                    code_nums.add(_norm(n))
                continue
            if s0 > prev_string_end + 1 or sblock is None or s0 in doc_starts:
                sblock = ("s", s0, 0)
            prev_string_end = t.end[0]
            para = sblock
            for k, sl in enumerate(body.splitlines()):
                if not sl.strip():
                    para = ("s", s0, k)
                    continue
                items.append((s0 + k, sl, para))
    return _dated(items), code_nums


def _js_lines(text: str):
    items, code_nums = [], set()
    in_block, bid = False, None
    prev_line_comment, lblock = -10, None
    for i, line in enumerate(text.splitlines(), 1):
        code = line
        if in_block:
            end = line.find("*/")
            items.append((i, line if end < 0 else line[:end], bid))
            if end < 0:
                continue
            in_block, code = False, line[end + 2:]
        start = code.find("/*")
        if start >= 0:
            end = code.find("*/", start)
            bid = ("b", i)
            items.append((i, code[start:] if end < 0 else code[start:end], bid))
            if end < 0:
                in_block, code = True, code[:start]
            else:
                code = code[:start] + code[end + 2:]
        c = re.search(r"(?<![:\"'`\\])//(.*)$", code)
        if c:
            if i != prev_line_comment + 1:
                lblock = ("l", i)
            prev_line_comment = i
            items.append((i, c.group(0), lblock))
            code = code[:c.start()]
        for m in re.finditer(r"([\"'`])((?:(?!\1).){6,})\1|>([^<>{}]{6,})<|^\s*([A-Za-z][^<>{}=;]{12,})$", code):
            s = m.group(2) or m.group(3) or m.group(4) or ""
            if m.group(4) and re.search(r"\w+:\s*['\"`]", s):
                continue                            # an object literal ({ Jul: '07', ... }), not text on a page
            if len(re.findall(r"[A-Za-z]{3,}", s)) >= 3:
                items.append((i, s, ("t", i)))
        for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])", re.sub(r"([\"'`]).*?\1", "", code)):
            code_nums.add(_norm(n))
    return _dated(items), code_nums


def _comment_lines(text: str, marker: str):
    """SQL (--), shell/YAML/TOML (#), HTML (<!-- -->): the comments are the statements; the rest is code."""
    items, code_nums = [], set()
    prev, block = -10, None
    in_html = False
    for i, line in enumerate(text.splitlines(), 1):
        if marker == "<!--":
            seg, code = "", line
            if in_html or "<!--" in line:
                start = 0 if in_html else line.find("<!--")
                end = line.find("-->", start)
                seg = line[start:] if end < 0 else line[start:end]
                code = line[:start] + ("" if end < 0 else line[end + 3:])
                in_html = end < 0
            if seg.strip():
                items.append((i, seg, ("h", i)))
        else:
            pos = line.find(marker) if marker == "--" else (line.find(marker) if not line.lstrip().startswith("#!") else -1)
            seg, code = (line[pos:], line[:pos]) if pos >= 0 else ("", line)
            if seg.strip():
                if i != prev + 1:
                    block = ("c", i)
                prev = i
                items.append((i, seg, block))
        for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])", re.sub(r"(['\"]).*?\1", "", code)):
            code_nums.add(_norm(n))
    return _dated(items), code_nums


_PARAMS_NUMS: set[str] | None = None


def params_numbers() -> set[str]:
    """The project's named settings: every numeric literal of analytics/params.py, and every number assigned to an
    UPPER_CASE module-level constant in any tracked Python file under analytics/, backend/ or scripts/ (a number, or the
    numbers of a tuple, list or dict). A comment or on-screen sentence stating one of them states that setting (a
    definition), wherever it is written. A value that is a setting in one module and a measurement in another sentence
    passes as the setting: a stated limit of the check."""
    global _PARAMS_NUMS
    if _PARAMS_NUMS is None:
        src = (REPO / "analytics" / "params.py").read_text(encoding="utf-8")
        nums = {_norm(t.string) for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type == tokenize.NUMBER}
        for f in tracked_files():
            if not f.endswith(".py") or not f.startswith(("analytics/", "backend/", "scripts/")) or f.startswith("scripts/archive/"):
                continue
            try:
                tree = ast.parse((REPO / f).read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if any(isinstance(t, ast.Name) and t.id.isupper() for t in targets) and node.value is not None:
                        for c in ast.walk(node.value):
                            if isinstance(c, ast.Constant) and isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                                nums.add(_norm(repr(c.value)))
        _PARAMS_NUMS = nums
    return _PARAMS_NUMS


EXAMPLE = re.compile(r"\be\.g\.|\bfor example\b|\bfor instance\b|\bsuch as\b|\bi\.e\.", re.I)


def _norm(n: str) -> str:
    n = n.replace(",", "").replace("_", "").strip().rstrip("%").strip()
    try:
        v = float(n)
    except ValueError:
        return n
    return repr(round(v, 9))


def _is_definition(fig: str, code_nums: set[str]) -> bool:
    n = _norm(fig)
    if n in code_nums:
        return True
    if fig.strip().endswith("%"):
        try:
            v = float(fig.replace(",", "").rstrip("% "))
            return repr(round(v / 100, 9)) in code_nums
        except ValueError:
            return False
    return False


# ---------------------------------------------------------------- the ledger
def load_ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    return sorted(p for p in out.decode("utf-8").split("\0") if p)


def classify(path: str, rules: list[dict]) -> dict | None:
    for r in rules:
        if any(fnmatch.fnmatchcase(path, g) for g in r["globs"]):
            return r
    return None


def _read(path: str) -> str | None:
    p = REPO / path
    if p.suffix.lower() not in TEXT_EXT or not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


NOT_CLAIM_KINDS = ("example", "definition", "identifier", "manuscript-quote")


def scan(path: str, rule: dict, checked: list[dict], not_claims: list[dict] | None = None,
         dated_entries: list[dict] | None = None) -> list[Figure]:
    text = _read(path)
    if text is None:
        return []
    cls = rule["class"]
    ext = Path(path).suffix.lower()
    if cls not in ("current", "code"):
        if ext in (".csv", ".json") and cls in ("data", "generated", "record"):
            return []                               # data cells: traced as a whole file by the rule, not one by one
        return [Figure(path, i, f, ln.strip()[:200], cls) for i, ln in enumerate(text.splitlines(), 1) for f in figures_in(ln)]
    if ext == ".py":
        lines, code_nums = _py_lines(text)
    elif ext in (".js", ".jsx"):
        lines, code_nums = _js_lines(text)
    elif cls == "code" and ext == ".sql":
        lines, code_nums = _comment_lines(text, "--")
    elif cls == "code" and ext in (".sh", ".yaml", ".yml", ".toml"):
        lines, code_nums = _comment_lines(text, "#")
    elif cls == "code" and ext == ".html":
        lines, code_nums = _comment_lines(text, "<!--")
    elif cls == "code" and ext in (".json", ".css", ".txt"):
        return []                                   # configuration and data, no prose
    else:
        lines, code_nums = _md_lines(text), set()
    if cls == "code":
        code_nums = code_nums | params_numbers()
    pats = [(re.compile(c["pattern"]), c) for c in checked if c["file"] == path]
    nots = [(re.compile(c["pattern"]), c) for c in (not_claims or []) if c["file"] == path]
    # a ledger-side date, for files a comment edit must not touch (the month-load attestation hashes them: CLAUDE.md, "The gate")
    ledger_dated = [re.compile(c["pattern"]) for c in (dated_entries or []) if c["file"] == path]
    as_of = bool(FIGURES_AS_OF.search("\n".join(text.splitlines()[:12])))
    out = []
    for i, ln, dated in lines:
        figs = figures_in(ln, code=cls == "code")
        if not figs:
            continue
        status = None
        if UNTRACEABLE.search(ln):
            status = "untraceable"
        elif dated or as_of or any(p.search(ln) for p in ledger_dated):
            status = "dated"
        elif cls == "code" and EXAMPLE.search(ln):
            status = "example"
        # a `checked` entry covers the figures it names (all on the line when it names none)
        covered = set()
        for p, c in pats:
            if p.search(ln):
                covered |= set(c.get("figures") or figs)
        # a `not_claims` entry: the figure is not a statement about data (an example of output, a definition of the code,
        # an identifier, a manuscript sentence quoted to place a citation), named and explained in the ledger
        kinds = {}
        for p, c in nots:
            if p.search(ln):
                for f in (c.get("figures") or figs):
                    kinds[f] = c["kind"]
        for f in figs:
            st = "checked" if f in covered and status != "untraceable" else status
            st = st or kinds.get(f) or ("definition" if code_nums and _is_definition(f, code_nums) else "residue")
            out.append(Figure(path, i, f, ln.strip()[:200], st))
    return out


# ---------------------------------------------------------------- the check
def verify() -> int:
    led = load_ledger()
    rules, checked = led["rules"], led["checked"]
    problems: list[str] = []
    for r in rules:
        if r["class"] not in CLASSES:
            problems.append(f"ledger rule {r['globs']}: unknown class {r['class']!r}")
        if r["class"] == "generated":
            gen = r.get("generator")
            if not gen or not (REPO / gen.split()[0]).exists():
                problems.append(f"ledger rule {r['globs']}: generator {gen!r} does not exist")
            ver = r.get("verifier")
            if ver is None and not r.get("why_no_verifier"):
                problems.append(f"ledger rule {r['globs']}: no verifier and no reason")
            if ver and ver not in CHECK_SH.read_text(encoding="utf-8"):
                problems.append(f"ledger rule {r['globs']}: verifier {ver!r} is not run by scripts/check.sh")
        if r["class"] == "record" and r.get("dated") is not None and not ISO.search(r["dated"]):
            problems.append(f"ledger rule {r['globs']}: `dated` must carry an ISO date: {r['dated']!r}")
    files = tracked_files()
    counts: dict[str, int] = {}
    residue: list[Figure] = []
    untraceable: list[Figure] = []
    for f in files:
        r = classify(f, rules)
        if r is None:
            problems.append(f"{f}: no ledger rule classifies this file (add one to docs/FIGURE_PROVENANCE.json)")
            continue
        if r["class"] == "record" and f.lower().endswith(".md") and not r.get("dated"):
            head = "\n".join((_read(f) or "").splitlines()[:8])
            if not BANNER.search(head):
                problems.append(f"{f}: a dated record without the label `Dated record (<ISO date>` in its first 8 lines")
        for fig in scan(f, r, checked, led.get("not_claims", []), led.get("dated", [])):
            counts[fig.status] = counts.get(fig.status, 0) + 1
            if fig.status == "residue":
                residue.append(fig)
            elif fig.status == "untraceable":
                untraceable.append(fig)
    # every `checked` entry must still match its file and name a test that exists
    for c in checked:
        text = _read(c["file"]) or ""
        if not re.search(c["pattern"], text, re.M):
            problems.append(f"checked entry {c['file']} {c['pattern']!r}: matches no line (the sentence moved or the check is stale)")
        tfile, _, tname = c["by"].partition("::")
        if not (REPO / tfile).exists() or (tname and f"def {tname}" not in (REPO / tfile).read_text(encoding="utf-8")):
            problems.append(f"checked entry {c['file']}: test {c['by']!r} does not exist")
        if "params" in c:
            problems.extend(_param_problem(c, text))
    # every `not_claims` entry must still match a line, say what kind of non-claim it is, and say why
    for c in led.get("not_claims", []):
        text = _read(c["file"]) or ""
        if not re.search(c["pattern"], text, re.M):
            problems.append(f"not_claims entry {c['file']} {c['pattern']!r}: matches no line (remove it, or follow the sentence)")
        if c.get("kind") not in NOT_CLAIM_KINDS:
            problems.append(f"not_claims entry {c['file']} {c['pattern']!r}: kind must be one of {NOT_CLAIM_KINDS}")
        if len(c.get("note", "")) < 12:
            problems.append(f"not_claims entry {c['file']} {c['pattern']!r}: needs a note saying why the figure is not a claim")
    # every ledger-side `dated` entry must still match a line and carry the date and where it comes from
    for c in led.get("dated", []):
        text = _read(c["file"]) or ""
        if not re.search(c["pattern"], text, re.M):
            problems.append(f"dated entry {c['file']} {c['pattern']!r}: matches no line (remove it, or follow the sentence)")
        if not ISO.fullmatch(c.get("date", "")) or len(c.get("source", "")) < 8:
            problems.append(f"dated entry {c['file']} {c['pattern']!r}: needs an ISO `date` and a `source` (the commit that wrote it)")
    for fig in residue:
        problems.append(f"{fig.file}:{fig.line}: {fig.figure!r} is neither dated, checked, a definition nor marked "
                        f"UNTRACEABLE: {fig.text[:120]}")
    print("figure provenance: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for where in sorted({(fig.file, fig.line, fig.text) for fig in untraceable}):
        print(f"  UNTRACEABLE (listed, not passed): {where[0]}:{where[1]} {where[2][:140]}")
    if problems:
        for p in problems[:400]:
            print("FAIL " + p)
        if len(problems) > 400:
            print(f"FAIL ... and {len(problems) - 400} more")
        print(f"RED: {len(problems)} provenance problem(s)")
        return 1
    print(f"GREEN: {len(files)} tracked files classified; every figure in a current file or a code comment is dated, checked "
          f"against live or its source, a definition of the code beside it, or marked UNTRACEABLE "
          f"({len({(f.file, f.line) for f in untraceable})} line(s) listed)")
    return 0


def _param_problem(c: dict, text: str) -> list[str]:
    """A `checked` entry with `params` (a static check, no database): capture group k of the pattern must equal spec k, either
    a constant of the code ({"name": "analytics.params.LP_WEIGHTS", "key": "cost", "scale": 1}) or the stripped contents of a
    tracked file ({"file": ".python-version"})."""
    m = re.search(c["pattern"], text, re.M)
    if not m:
        return []
    out = []
    for k, spec in enumerate(c["params"], 1):
        got = m.group(k).replace(",", "")
        if "file" in spec:
            want = (REPO / spec["file"]).read_text(encoding="utf-8").strip()
            if got != want:
                out.append(f"checked entry {c['file']}: states {got!r}, {spec['file']} holds {want!r}")
            continue
        mod, _, name = spec["name"].rpartition(".")
        try:
            val = getattr(importlib.import_module(mod), name)
        except (ImportError, AttributeError) as e:
            out.append(f"checked entry {c['file']}: {spec['name']} cannot be read ({e})")
            continue
        if spec.get("key") is not None:
            val = val[spec["key"]]
        want = float(val) * float(spec.get("scale", 1))
        if abs(float(got) - want) > 1e-9 * max(1.0, abs(want)):
            out.append(f"checked entry {c['file']}: states {got}, {spec['name']}"
                       f"{'[' + repr(spec['key']) + ']' if spec.get('key') is not None else ''} gives {want:g}")
    return out


def inventory(path: Path) -> int:
    led = load_ledger()
    rows = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "line", "class", "status", "figure", "text"])
        for f in tracked_files():
            r = classify(f, led["rules"])
            if r is None:
                continue
            for fig in scan(f, r, led["checked"], led.get("not_claims", []), led.get("dated", [])):
                w.writerow([fig.file, fig.line, r["class"], fig.status, fig.figure, fig.text])
                rows += 1
    print(f"{rows} figures written to {path}")
    return 0


def residue_report() -> int:
    led = load_ledger()
    by_file: dict[str, list[Figure]] = {}
    for f in tracked_files():
        r = classify(f, led["rules"])
        if r is None or r["class"] not in ("current", "code"):
            continue
        for fig in scan(f, r, led["checked"], led.get("not_claims", []), led.get("dated", [])):
            if fig.status == "residue":
                by_file.setdefault(f, []).append(fig)
    total = sum(len(v) for v in by_file.values())
    for f, figs in sorted(by_file.items(), key=lambda kv: -len(kv[1])):
        print(f"{len(figs):5d} {f}")
    print(f"{total} residue figures in {len(by_file)} files")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--verify", action="store_true")
    g.add_argument("--inventory", nargs="?", const=str(REPO / "local" / "figure_inventory.csv"))
    g.add_argument("--residue", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.verify:
        return verify()
    if a.residue:
        return residue_report()
    return inventory(Path(a.inventory))


if __name__ == "__main__":
    sys.exit(main())
