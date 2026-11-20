#!/usr/bin/env python3
"""make_examples.py - regenerate submission/examples/*/out and run.txt from the real tool (nothing is typed by hand).
The inputs are fictional (authors, journals, DOIs with the unregistered prefix 10.9999)."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SUB = os.path.join(ROOT, "submission") if os.path.isdir(os.path.join(ROOT, "submission")) else ROOT  # work tree or repository layout
EX = os.path.join(SUB, "examples")
CL = os.path.join(SUB, "scripts", "cl.py")
KEEP = {"md": ("manuscript.md", "references.apa7.txt", "references.bib", "changes.md", "numbering_map.csv", "review_checklist.md", "result.json"),
        "tex": ("manuscript.tex", "changes.md", "review_checklist.md"),
        "apa": ("manuscript.md", "changes.md"),
        "zh": ("manuscript.txt", "references.gbt7714.txt", "changes.md")}  # the submission is limited to 50 files: keep the informative ones


def scrub(text, *paths):
    """no local paths in anything we publish"""
    for p in sorted(set(x for x in paths if x), key=len, reverse=True):
        text = text.replace(p, "<dir>")
    text = re.sub(r"/(?:Users|home|var/folders)/[^\s\"',)]*", "<dir>", text)
    return re.sub(r"<dir>/tmp\w+", "<work>", text)  # the work folder is a random temporary one


def sh(args, log):
    r = subprocess.run([sys.executable, CL] + args, capture_output=True, text=True, cwd=EX)
    shown = " ".join(os.path.relpath(a, EX) if os.path.isabs(a) and a.startswith(EX) else a for a in args)
    log.write(scrub("$ cl.py " + shown + "\n" + r.stdout + r.stderr + "\n", EX, tempfile.gettempdir()))
    return r


def finish(out, name, log):
    log.close()
    for f in os.listdir(out):
        if f not in KEEP[name]:
            os.remove(os.path.join(out, f)) if os.path.isfile(os.path.join(out, f)) else shutil.rmtree(os.path.join(out, f))
    shutil.move(os.path.join(tempfile.gettempdir(), "run_%s.txt" % name), os.path.join(EX, name, "run.txt"))


def example(name, args_run, decisions=None, build_extra=(), manuscript_override=None):
    out = os.path.join(EX, name, "out")
    shutil.rmtree(out, ignore_errors=True)
    work = tempfile.mkdtemp()
    log = open(os.path.join(tempfile.gettempdir(), "run_%s.txt" % name), "w", encoding="utf-8")
    sh(["run"] + args_run + ["--out", out, "--work", work], log)
    if decisions:
        sh(["ingest", work, decisions], log)
        sh(["build", work, "--out", out] + list(build_extra), log)
    finish(out, name, log)
    shutil.rmtree(work, ignore_errors=True)


def main():
    example("md", ["md/manuscript.md", "--lib", "md/library.bib", "--lib", "md/library.ris"], "md/decisions.txt")
    example("tex", ["tex/paper.tex"], "tex/decisions.txt")
    example("apa", ["apa/manuscript.md", "--lib", "md/library.bib", "--lib", "md/library.ris"])
    # Chinese Word manuscript with superscript markers and GB/T 7714 list (built from the text spec)
    tmp = tempfile.mkdtemp()
    sys.path.insert(0, HERE)
    import make_docx
    make_docx.make(open(os.path.join(HERE, "fixtures", "zh_manuscript_spec.txt"), encoding="utf-8").read().splitlines(), os.path.join(tmp, "manuscript.docx"))
    os.makedirs(os.path.join(EX, "zh"), exist_ok=True)
    shutil.copy(os.path.join(HERE, "fixtures", "zh_manuscript_spec.txt"), os.path.join(EX, "zh", "manuscript_spec.txt"))
    out = os.path.join(EX, "zh", "out")
    shutil.rmtree(out, ignore_errors=True)
    log = open(os.path.join(tempfile.gettempdir(), "run_zh.txt"), "w", encoding="utf-8")
    work = tempfile.mkdtemp()
    sh(["run", os.path.join(tmp, "manuscript.docx"), "--out", out, "--work", work], log)
    x = zipfile.ZipFile(os.path.join(out, "manuscript.docx")).read("word/document.xml").decode("utf-8")
    paras = re.findall(r"<w:p>.*?</w:p>", x)
    txt = []
    for p in paras:
        p = re.sub(r'<w:r><w:rPr><w:vertAlign w:val="superscript" ?/></w:rPr><w:t[^>]*>([^<]*)</w:t></w:r>', r"^{\1}", p)
        txt.append(re.sub(r"<[^>]+>", "", p))
    open(os.path.join(out, "manuscript.txt"), "w", encoding="utf-8").write("\n".join(txt) + "\n")
    finish(out, "zh", log)
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
