#!/usr/bin/env python3
"""Regression tests for citation-ledger (stdlib unittest). Run: python3 dev/test_all.py [-v]
Inputs are fictional or generated; nothing needs the network."""
import argparse
import warnings
import contextlib
import io
import json
import os
import random
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SUB = os.path.join(ROOT, "submission") if os.path.isdir(os.path.join(ROOT, "submission")) else ROOT  # work tree or repository layout
SCR = os.path.join(SUB, "scripts")
sys.path.insert(0, SCR)
sys.path.insert(0, HERE)
import bib  # noqa: E402
import cite  # noqa: E402
import cl  # noqa: E402
import dedupe  # noqa: E402
import fmt  # noqa: E402
import make_docx  # noqa: E402
import verify  # noqa: E402


warnings.simplefilter("ignore", ResourceWarning)


def run(*args):
    """cl.main with captured stdout; returns (exit_code, text)"""
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            cl.main(list(args))
        except SystemExit as e:
            code = e.code or 0
    return code, buf.getvalue()


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *p):
        return os.path.join(self.tmp, *p)

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.path(name)


# ------------------------------------------------------------------------------------------------ reading references
class TestAuthors(unittest.TestCase):
    def fam(self, s):
        return [(a["family"], a["given"]) for a in bib.split_authors(s)]

    def test_apa_three(self):
        self.assertEqual(self.fam("Lindqvist, M., Okafor, T., & Brandt, L."), [("Lindqvist", "M."), ("Okafor", "T."), ("Brandt", "L.")])

    def test_apa_two_initials(self):
        self.assertEqual(self.fam("Smith, J. A., & Lee, K."), [("Smith", "J. A."), ("Lee", "K.")])

    def test_ieee_initials_first(self):
        self.assertEqual([a["family"] for a in bib.split_authors("T. Okafor and M. Lindqvist")], ["Okafor", "Lindqvist"])

    def test_gbt_caps(self):
        a = bib.split_authors("FAN X, LI Y, WANG Z")
        self.assertEqual([(x["family"].lower(), x["given"]) for x in a], [("fan", "X"), ("li", "Y"), ("wang", "Z")])

    def test_chinese_compound_surname(self):
        a = bib.split_authors("欧阳明, 王伟")
        self.assertEqual((a[0]["family"], a[0]["given"]), ("欧阳", "明"))
        self.assertEqual(len(a), 2)


class TestParsers(unittest.TestCase):
    BIB = "@article{k1, author={Doe, Jane and Roe, Richard}, title={A {Study} of \\'e things}, journal={J. Test}, year=2020, volume={3}, number={2}, pages={10--20}, doi={10.9999/x.1}}\n@book{k2, author={Poe, Ed}, title={Ravens}, publisher={Press}, address={Rome}, year={1999}, isbn={9780306406157}}"
    RIS = "TY  - JOUR\nAU  - Doe, Jane\nTI  - A Study\nJO  - J. Test\nPY  - 2020\nVL  - 3\nIS  - 2\nSP  - 10\nEP  - 20\nDO  - 10.9999/x.1\nER  - \n"
    ENW = "%0 Journal Article\n%A Doe, Jane\n%T A Study\n%J J. Test\n%D 2020\n%V 3\n%N 2\n%P 10-20\n%R 10.9999/x.1\n\n"
    CSL = json.dumps([{"id": "c1", "type": "article-journal", "title": "A Study", "author": [{"family": "Doe", "given": "Jane"}], "container-title": "J. Test", "issued": {"date-parts": [[2020]]}, "volume": "3", "issue": "2", "page": "10-20", "DOI": "10.9999/x.1"}])
    NE = "{Reference Type}: Journal Article\n{Author}: Doe, Jane\n{Title}: A Study\n{Journal}: J. Test\n{Year}: 2020\n{Volume}: 3\n{Issue}: 2\n{Pages}: 10-20\n{DOI}: 10.9999/x.1\n"

    def test_all_formats_agree(self):
        for name, text, fn in (("x.bib", self.BIB, None), ("x.ris", self.RIS, None), ("x.enw", self.ENW, None), ("x.json", self.CSL, None), ("x.txt", self.NE, None)):
            kind, recs = bib.parse_any(text, name)
            r = recs[0]
            self.assertEqual((r["year"], r["volume"], r["issue"], r["pages"], r["doi"]), ("2020", "3", "2", "10-20", "10.9999/x.1"), kind)
            self.assertEqual(r["authors"][0]["family"], "Doe", kind)
            self.assertEqual(r["type"], "journal", kind)

    def test_bibtex_latex_and_isbn(self):
        _, recs = bib.parse_any(self.BIB, "x.bib")
        self.assertIn("é", recs[0]["title"])
        self.assertEqual(recs[1]["type"], "book")
        self.assertEqual(recs[1]["isbn"].replace("-", ""), "9780306406157")

    def test_text_entries(self):
        cases = [
            ("[1] 张三, 李四. 屋顶绿化研究[J]. 建筑学报, 2019, 12(3): 45-52.", ("journal", "2019", "12", "3", "45-52")),
            ("Doe, J., & Roe, R. (2020). A study of things. Journal of Tests, 3(2), 10-20. https://doi.org/10.9999/x.1", ("journal", "2020", "3", "2", "10-20")),
            ('J. Doe and R. Roe, "A study of things," J. Tests, vol. 3, no. 2, pp. 10-20, 2020.', ("journal", "2020", "3", "2", "10-20")),
            ("Doe J, Roe R. A study of things. J Tests. 2020;3(2):10-20.", ("journal", "2020", "3", "2", "10-20")),
        ]
        for raw, want in cases:
            r = bib.parse_text_entry(raw)
            self.assertEqual((r["type"], r["year"], r["volume"], r["issue"], r["pages"]), want, raw)

    def test_arxiv_preprint_type(self):
        r = bib.parse_text_entry("Haddad, S., & Moreau, C. (2022). Cooling savings. arXiv preprint arXiv:2203.00001.")
        self.assertEqual((r["type"], r["arxiv"]), ("preprint", "2203.00001"))

    def test_unparsable_is_flagged_not_invented(self):
        r = bib.parse_text_entry("see the lab notebook, page 4")
        self.assertLess(r["parse"]["confidence"], 0.5)
        self.assertEqual(r["authors"], [])


# ------------------------------------------------------------------------------------------------ markers
class TestMarkers(unittest.TestCase):
    def styles(self, text):
        return [(i["style"], i.get("nums") or i.get("keys") or i.get("ay")) for i in cite.find_instances(text, "P1")]

    def test_bracket_forms(self):
        self.assertEqual(self.styles("a [1] b [2,3] c [4–6] d [7, 9]."), [("bracket", [1]), ("bracket", [2, 3]), ("bracket", [4, 5, 6]), ("bracket", [7, 9])])

    def test_superscripts(self):
        self.assertEqual(self.styles("x<sup>1,2</sup> y^3^ z¹²"), [("sup", [1, 2]), ("sup", [3]), ("sup", [12])])

    def test_latex_pandoc(self):
        got = self.styles(r"a \cite{k1,k2} b \citep[p.~3]{k3} c [@k4; @k5]")
        self.assertEqual(got, [("latex", ["k1", "k2"]), ("latex", ["k3"]), ("pandoc", ["k4", "k5"])])

    def test_author_year(self):
        got = self.styles("(Smith & Lee, 2020; Wang et al., 2019a) and Brown (2018).")
        self.assertEqual(got[0][0], "authyear")
        self.assertEqual([y for _, y in got[0][1]], ["2020", "2019a"])
        self.assertEqual(got[1][1][0][1], "2018")

    def test_not_citations(self):
        self.assertEqual(self.styles("In 2020 (Figure 3) the value (p < 0.05) rose; see Table [A]."), [])

    def test_compress(self):
        self.assertEqual(cite.compress([1, 2, 3, 5, 7, 8]), "1–3,5,7,8")
        self.assertEqual(cite.compress([4, 5], min_run=3), "4,5")
        self.assertEqual(cite.expand("1-3,5"), [1, 2, 3, 5])

    def test_render_keeps_form(self):
        inst = {"style": "sup", "form": {"tag": "html"}}
        self.assertEqual(cite.render_marker(inst, [1, 2, 3]), "<sup>1–3</sup>")
        self.assertEqual(cite.render_marker({"style": "bracket"}, [2, 3], space=True), "[2, 3]")


# ------------------------------------------------------------------------------------------------ formatting
class TestFormat(unittest.TestCase):
    def rec(self, **kw):
        r = bib.new_record("test")
        r.update({"type": "journal", "title": "A study of things", "container": "Journal of Tests", "year": "2020", "volume": "3", "issue": "2", "pages": "10-20"})
        r["authors"] = bib.split_authors(kw.pop("authors", "Doe, J. A., & Roe, R."))
        r.update(kw)
        return bib.finish(r)

    def test_gbt_journal(self):
        self.assertEqual(fmt.format_entry(self.rec(), "gbt7714"), "DOE J A, ROE R. A study of things[J]. Journal of Tests, 2020, 3(2): 10-20.")

    def test_gbt_et_al_after_three(self):
        s = fmt.format_entry(self.rec(authors="A, B., C, D., E, F., G, H."), "gbt7714")
        self.assertIn("et al", s)

    def test_gbt_chinese(self):
        r = self.rec(authors="张三, 李四", title="屋顶绿化研究", container="建筑学报")
        self.assertEqual(fmt.format_entry(r, "gbt7714"), "张三, 李四. 屋顶绿化研究[J]. 建筑学报, 2020, 3(2): 10-20.")

    def test_apa_ieee_vancouver(self):
        r = self.rec(doi="10.9999/x.1")
        self.assertTrue(fmt.format_entry(r, "apa7").startswith("Doe, J. A., & Roe, R. (2020). A study of things."))
        self.assertIn("https://doi.org/10.9999/x.1", fmt.format_entry(r, "apa7"))
        self.assertTrue(fmt.format_entry(r, "ieee").startswith('J. A. Doe and R. Roe, "A study of things,"'))
        self.assertIn("2020;3(2):10", fmt.format_entry(r, "vancouver"))

    def test_missing_fields_not_invented(self):
        r = self.rec(volume="", issue="", pages="")
        s = fmt.format_entry(r, "gbt7714")
        self.assertNotIn("None", s)
        self.assertNotIn("()", s)

    def test_bibtex_ris_export_roundtrip(self):
        r = self.rec(doi="10.9999/x.1")
        _, b = bib.parse_any(fmt.to_bibtex([r]), "x.bib")
        _, ri = bib.parse_any(fmt.to_ris([r]), "x.ris")
        for x in (b[0], ri[0]):
            self.assertEqual((x["title"], x["year"], x["volume"], x["pages"], x["doi"]), (r["title"], "2020", "3", "10-20", "10.9999/x.1"))


# ------------------------------------------------------------------------------------------------ duplicates and verification
class TestDedupe(unittest.TestCase):
    def mk(self, title, authors, year, **kw):
        r = bib.new_record("t")
        r.update({"title": title, "year": year, "type": "journal", "container": kw.pop("container", "J")})
        r["authors"] = bib.split_authors(authors)
        r.update(kw)
        return bib.finish(r)

    def test_same_doi(self):
        a, b = self.mk("X", "A, B.", "2020", doi="10.9999/q"), self.mk("Different words entirely", "C, D.", "2019", doi="10.9999/q")
        self.assertEqual(dedupe.compare(a, b)["decision"], "same")

    def test_homonym_guard(self):
        a = self.mk("Introduction to the special issue on soils", "Smith, J.", "2020", container="Soil A")
        b = self.mk("Introduction to the special issue on soils", "Jones, K.", "2020", container="Soil B")
        self.assertEqual(dedupe.compare(a, b)["decision"], "different")

    def test_same_author_year_different_work(self):
        a = self.mk("Heat transfer in porous media under pulsed loading", "Wang, L.", "2019", pages="1-10")
        b = self.mk("Bacterial communities of alpine lake sediments", "Wang, L.", "2019", pages="55-70")
        self.assertEqual(dedupe.compare(a, b)["decision"], "different")

    def test_preprint_published(self):
        a = self.mk("Neighbourhood-scale cooling savings from roof vegetation", "Haddad, S., & Moreau, C.", "2022", type="preprint", container="arXiv", arxiv="2203.00001")
        b = self.mk("Neighbourhood-scale cooling savings from roof vegetation", "Haddad, S., & Moreau, C.", "2023", doi="10.9999/j.1")
        c = dedupe.compare(a, b)
        self.assertEqual(c["decision"], "same")
        self.assertTrue(c["work_pair"])

    def test_bilingual(self):
        a = self.mk("基于深度学习的滑坡识别", "王伟, 李明", "2021", container="地质学报", volume="95", issue="3", pages="100-110")
        b = self.mk("Deep learning based landslide identification", "Wang, W., Li, M.", "2021", container="Acta Geologica Sinica", volume="95", issue="3", pages="100-110")
        self.assertEqual(dedupe.compare(a, b)["decision"], "same")

    def test_clusters_and_canonical(self):
        a = self.mk("Cooling savings from roofs", "Haddad, S.", "2022", type="preprint", container="arXiv", arxiv="2203.00001")
        a["id"] = "a"
        b = self.mk("Cooling savings from roofs", "Haddad, S.", "2023", doi="10.9999/j.1")
        b["id"] = "b"
        cl_, cands, guarded = dedupe.clusters([a, b])
        self.assertEqual(cl_[0]["canonical"], "b")


class TestVerify(unittest.TestCase):
    def test_structural(self):
        r = bib.new_record("t")
        r.update({"title": "T", "year": "2020", "authors": bib.split_authors("A, B."), "type": "book", "isbn": "9780306406158", "pages": "20-10"})
        p = verify.structural(bib.finish(r))
        self.assertTrue(any("ISBN" in x for x in p))
        self.assertTrue(any("decreasing" in x for x in p))
        r["isbn"], r["pages"], r["year"] = "9780306406157", "10-20", "2099"
        self.assertTrue(any("year" in x for x in verify.structural(bib.finish(r))))

    def test_online_fails_fast_without_network(self):
        import urllib.request
        orig = urllib.request.urlopen
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise OSError("network is unreachable")
        urllib.request.urlopen = boom
        try:
            recs = [bib.finish({**bib.new_record("t"), "id": "r%d" % i, "title": "Title %d about something" % i, "year": "2020", "authors": bib.split_authors("A, B."), "type": "journal", "container": "J", "doi": "10.1/x%d" % i}) for i in range(8)]
            res = verify.check_all(recs, online=True, timeout=1)
        finally:
            urllib.request.urlopen = orig
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(v["status"] == "unchecked" for v in res.values()))

    def test_chinese_and_books_without_doi_are_not_called_fabricated(self):
        import urllib.request
        orig = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no lookup expected"))
        try:
            zh = bib.finish({**bib.new_record("t"), "id": "z", "title": "屋顶绿化研究", "year": "2020", "authors": bib.split_authors("张三"), "type": "journal", "container": "建筑学报"})
            bk = bib.finish({**bib.new_record("t"), "id": "b", "title": "A handbook of roofs", "year": "2001", "authors": bib.split_authors("Doe, J."), "type": "book", "publisher": "Press"})
            res = verify.check_all([zh, bk], online=True, timeout=1)
        finally:
            urllib.request.urlopen = orig
        self.assertEqual({v["status"] for v in res.values()}, {"unchecked"})
        self.assertIn("CNKI", res["z"]["details"][0])

    def test_offline_never_verified(self):
        r = bib.finish({**bib.new_record("t"), "title": "T", "year": "2020", "authors": bib.split_authors("A, B."), "type": "journal", "id": "x"})
        self.assertEqual(verify.check_all([r], online=False)["x"]["status"], "unchecked")


# ------------------------------------------------------------------------------------------------ end to end
MD = """# T

## Intro

Alpha holds [3]. Beta was shown [1,2]; gamma follows [5], and delta [3, 4, 5, 6]. Epsilon is uncited here.

## References

[1] Aaa, A. (2001). Title one about alpha. Journal One, 1(1), 1-10.
[2] Bbb, B. (2002). Title two about beta. Journal One, 2(1), 11-20.
[3] Ccc, C. (2003). Title three about gamma. Journal Two, 3(1), 21-30.
[4] Ddd, D. (2004). Title four about delta. Journal Two, 4(1), 31-40.
[5] Eee, E. (2005). Title five about epsilon. Journal Three, 5(1), 41-50.
[6] Fff, F. (2006). Title six about zeta. Journal Three, 6(1), 51-60.
[7] Ggg, G. (2007). Title seven never cited. Journal Four, 7(1), 61-70.
"""


class TestEndToEnd(TmpCase):
    def build(self, ms, *extra, decisions=None, style=None):
        work, out = self.path("w"), self.path("out")
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
        code, txt = run("prepare", ms, "--work", work, *extra)
        self.assertEqual(code, 0, txt)
        if decisions:
            c, t = run("ingest", work, self.write("dec.txt", decisions))
            self.assertEqual(c, 0, t)
        c, t = run("build", work, "--out", out, *(["--style", style] if style else []))
        return work, out, t

    def test_renumber_by_first_appearance_and_semantics_preserved(self):
        ms = self.write("m.md", MD)
        work, out, _ = self.build(ms)
        text = open(os.path.join(out, "manuscript.md"), encoding="utf-8").read()
        body = text.split("## References")[0]
        # first appearance order: 3,1,2,5,4,6 -> 1..6 ; range compressed
        self.assertIn("Alpha holds [1].", body)
        self.assertIn("[2,3]", body)
        # semantic check: every marker still points to the same work
        old_list = {int(m.group(1)): m.group(2) for m in re.finditer(r"^\[(\d+)\] (.*)$", MD, re.M)}
        new_list = {int(m.group(1)): m.group(2) for m in re.finditer(r"^\[(\d+)\] (.*)$", text, re.M)}
        self.assertEqual(sorted(new_list), list(range(1, len(new_list) + 1)))
        self.assertNotIn("never cited", " ".join(new_list.values()))
        # titles per marker, in text order
        def titles(lines_, lst):
            res = []
            for l in lines_:
                for it in cite.find_instances(l, "p"):
                    res += [re.search(r"Title (\w+)", lst[n]).group(1) if n in lst else "?" for n in it["nums"]]
            return res
        self.assertEqual(sorted(titles(MD.split("## References")[0].split("\n"), old_list)), sorted(titles(body.split("\n"), new_list)))
        self.assertEqual(titles(MD.split("## References")[0].split("\n"), old_list)[:5], titles(body.split("\n"), new_list)[:5])

    def test_idempotent(self):
        ms = self.write("m.md", MD)
        work, out, _ = self.build(ms)
        out_ms = os.path.join(out, "manuscript.md")
        w2, out2 = self.path("w2"), self.path("out2")
        run("prepare", out_ms, "--work", w2)
        c, t = run("build", w2, "--out", out2)
        self.assertEqual(open(out_ms, encoding="utf-8").read(), open(os.path.join(out2, "manuscript.md"), encoding="utf-8").read())
        L = json.load(open(os.path.join(w2, "ledger.json")))
        iss = cl.run_audit(json.load(open(os.path.join(w2, "doc.json"))), L)
        self.assertEqual([i["kind"] for i in iss if i["severity"] in ("error", "warn")], [])

    def sid_of(self, work, needle):
        doc = json.load(open(os.path.join(work, "doc.json")))
        for p in doc["paragraphs"]:
            for sn in p["sentences"]:
                if needle in p["text"][sn["start"]:sn["end"]]:
                    return sn["id"]
        raise AssertionError(needle)

    def test_insert_and_uncite_and_unresolved(self):
        ms = self.write("m.md", MD.replace("delta [3, 4, 5, 6]", "delta [3, 4, 5, 6] and zeta [9]"))
        work, out = self.path("w"), self.path("out")
        run("prepare", ms, "--work", work)
        dec = "=== cite %s\nkeys: L7\nafter: Epsilon is\n=== uncite %s\nkeys: 9\n" % (self.sid_of(work, "Epsilon"), self.sid_of(work, "Beta was shown"))
        c, t = run("ingest", work, self.write("dec.txt", dec))
        self.assertEqual(c, 0, t)
        run("build", work, "--out", out)
        text = open(os.path.join(out, "manuscript.md"), encoding="utf-8").read()
        self.assertRegex(text.split("## References")[0], r"Epsilon is \[\d\] uncited")
        ch = json.load(open(os.path.join(out, "changes.json")))
        self.assertEqual(len(ch["inserted"]), 1)

    def test_uncite_unresolved_marker(self):
        ms = self.write("m.md", MD.replace("gamma follows [5]", "gamma follows [5,9]"))
        work, out = self.path("w"), self.path("out")
        run("prepare", ms, "--work", work)
        c, t = run("ingest", work, self.write("dec.txt", "=== uncite %s\nkeys: 9\n" % self.sid_of(work, "gamma follows")))
        self.assertEqual(c, 0, t)
        run("build", work, "--out", out)
        self.assertNotIn("9", open(os.path.join(out, "manuscript.md"), encoding="utf-8").read().split("## References")[0])
        self.assertEqual(json.load(open(os.path.join(out, "result.json")))["status"], "success")

    def test_unresolved_stays_visible(self):
        ms = self.write("m.md", MD.replace("gamma follows [5]", "gamma follows [5,9]"))
        work, out, t = self.build(ms)
        res = json.load(open(os.path.join(out, "result.json")))
        self.assertEqual(res["status"], "partial")
        self.assertIn("?9", open(os.path.join(out, "manuscript.md"), encoding="utf-8").read())
        self.assertTrue(any(r["kind"] == "unresolved_citation" for r in res["human_review"]))

    def test_merge_redirects_markers(self):
        lib = self.write("lib.bib", "@article{dupA, author={Zed, Z.}, title={Title one about alpha}, journal={Journal One}, year={2001}, volume={1}, number={1}, pages={1--10}, doi={10.9999/dup}}\n@article{dupB, author={Zed, Z.}, title={Title one about alpha}, journal={J. One}, year={2001}, doi={10.9999/dup}}\n")
        ms = self.write("m.md", "Alpha is known [1]. Alpha again [2].\n\n## References\n\n[1] Zed, Z. (2001). Title one about alpha. Journal One, 1(1), 1-10. https://doi.org/10.9999/dup\n[2] Zed, Z. (2001). Title one about alpha. J. One. https://doi.org/10.9999/dup\n")
        work = self.path("w")
        run("prepare", ms, "--work", work, "--lib", lib)
        run("dedupe", work, "--auto")
        c, t = run("build", work, "--out", self.path("out"))
        text = open(self.path("out", "manuscript.md"), encoding="utf-8").read()
        self.assertEqual(text.count("Title one about alpha"), 1)
        self.assertRegex(text.split("## References")[0], r"\[1\].*\[1\]")

    def test_bilingual_pair_keeps_manuscript_language(self):
        ne = self.write("a.txt", "{Reference Type}: Journal Article\n{Author}: 王伟;李明\n{Title}: 基于深度学习的滑坡识别方法研究\n{Journal}: 地质学报\n{Year}: 2021\n{Volume}: 95\n{Issue}: 3\n{Pages}: 100-110\n")
        en = self.write("b.enw", "%0 Journal Article\n%A Wang, W.\n%A Li, M.\n%T Deep learning based landslide identification\n%J Acta Geologica Sinica\n%D 2021\n%V 95\n%N 3\n%P 100-110\n%R 10.9999/ags.1\n")
        ms = self.write("m.md", "滑坡识别已有进展[1]。\n\n## 参考文献\n\n[1] 王伟, 李明. 基于深度学习的滑坡识别方法研究[J]. 地质学报, 2021, 95(3): 100-110.\n")
        work, out, _ = self.build(ms, "--lib", ne, "--lib", en)
        c, t = run("dedupe", work, "--auto")
        self.assertIn("1 duplicate cluster", t)
        run("build", work, "--out", out)
        refs = open(os.path.join(out, "manuscript.md"), encoding="utf-8").read().split("## 参考文献")[1]
        self.assertIn("基于深度学习的滑坡识别方法研究[J]", refs)
        self.assertIn("10.9999/ags.1", refs)
        self.assertNotIn("Deep learning", refs)

    def test_unique_ids_across_files(self):
        a = self.write("a.bib", "@article{k, author={A, A.}, title={T one two three four}, journal={J}, year=2000}\n")
        b = self.write("b.bib", "@article{k, author={B, B.}, title={Other thing entirely different}, journal={J}, year=2001}\n")
        work = self.path("w")
        run("prepare", self.write("m.md", "x [1].\n"), "--work", work, "--lib", a, "--lib", b)
        L = json.load(open(os.path.join(work, "ledger.json")))
        self.assertEqual(len(L["entries"]), 2)

    def test_homonyms_not_merged_by_auto(self):
        ms = self.write("m.md", "A [1]. B [2].\n\n## References\n\n[1] Wang, L. (2019). Heat transfer in porous media under pulsed loading. Journal A, 1(1), 1-10.\n[2] Wang, L. (2019). Bacterial communities of alpine lake sediments. Journal B, 2(1), 55-70.\n")
        work = self.path("w")
        run("prepare", ms, "--work", work)
        c, t = run("dedupe", work, "--auto")
        self.assertIn("0 duplicate cluster", t)

    def test_latex(self):
        lib = self.write("lib.bib", "@article{a, author={A, A.}, title={T a}, journal={J}, year=2000}\n@article{b, author={B, B.}, title={T b}, journal={J}, year=2001}\n")
        ms = self.write("p.tex", "\\documentclass{article}\n\\begin{document}\nOne claim \\cite{a}. Another \\citep{b}.\n\\bibliography{lib}\n\\end{document}\n")
        work, out, _ = self.build(ms, "--lib", lib, decisions="=== cite S001\nkeys: b\n")
        text = open(os.path.join(out, "manuscript.tex"), encoding="utf-8").read()
        self.assertIn("\\cite{a}", text)
        self.assertIn("\\bibliography{references}", text)
        self.assertTrue(os.path.isfile(os.path.join(out, "references.bib")))

    def test_docx_superscript_roundtrip_and_tracked(self):
        spec = ["# Title", "# 1 Intro", "Alpha is known^{2}. Beta follows^{1,3}.", "# References",
                "[1] Aaa, A. (2001). First work. Journal One, 1(1), 1-10.", "[2] Bbb, B. (2002). Second work. Journal One, 2(1), 11-20.", "[3] Ccc, C. (2003). Third work. Journal Two, 3(1), 21-30."]
        docx = self.path("m.docx")
        make_docx.make(spec, docx)
        work, out, _ = self.build(docx)
        x = zipfile.ZipFile(os.path.join(out, "manuscript.docx")).read("word/document.xml").decode()
        self.assertEqual(len(re.findall(r'<w:vertAlign w:val="superscript" ?/>', x)), 2)
        self.assertIn(">1<", x)
        t = zipfile.ZipFile(os.path.join(out, "manuscript_tracked_changes.docx")).read("word/document.xml").decode()
        self.assertIn("<w:ins ", t)
        self.assertIn("<w:del ", t)
        import xml.dom.minidom as md
        md.parseString(t)
        paras = re.findall(r"<w:p>.*?</w:p>", x, re.S)
        refs = [re.sub(r"<[^>]+>", "", p) for p in paras if re.sub(r"<[^>]+>", "", p).startswith("[")]
        self.assertEqual(len(refs), 3)
        self.assertTrue(refs[0].startswith("[1] ") and "Second work" in refs[0])

    def test_docx_auto_numbered_reference_list(self):
        spec = ["# Title", "# 1 Intro", "Beta follows [2]. Alpha is known [1].", "# References",
                "@n Aaa, A. (2001). First work. Journal One, 1(1), 1-10.", "@n Bbb, B. (2002). Second work. Journal One, 2(1), 11-20.", "@n Ccc, C. (2003). Third work never cited. Journal Two, 3(1), 21-30."]
        docx = self.path("m.docx")
        make_docx.make(spec, docx)
        work, out, _ = self.build(docx)
        x = zipfile.ZipFile(os.path.join(out, "manuscript.docx")).read("word/document.xml").decode()
        paras = [re.sub(r"<[^>]+>", "", p) for p in re.findall(r"<w:p>.*?</w:p>", x, re.S)]
        self.assertIn("Beta follows [1]. Alpha is known [2].", paras)
        refs = [p for p in paras if "work" in p and "Journal" in p]
        self.assertEqual(len(refs), 2)  # the uncited entry is dropped
        self.assertIn("Second work", refs[0])
        self.assertFalse(refs[0].startswith("["))  # the list is auto-numbered by Word: no label typed into the text

    def test_marker_in_table_is_reported_not_damaged(self):
        ms = self.write("m.md", "Alpha [2]. Beta [1].\n\n| a | b |\n|---|---|\n| x [2] | y |\n\n## References\n\n[1] Aaa, A. (2001). First work. Journal One, 1(1), 1-10.\n[2] Bbb, B. (2002). Second work. Journal One, 2(1), 11-20.\n")
        work, out, _ = self.build(ms)
        text = open(os.path.join(out, "manuscript.md"), encoding="utf-8").read()
        self.assertIn("| x [2] | y |", text)  # untouched
        self.assertIn("Alpha [1]. Beta [2].", text)
        res = json.load(open(os.path.join(out, "result.json")))
        self.assertTrue(any(r["kind"] == "manual_marker_update" and "[2] must become [1]" in r["detail"] for r in res["human_review"]))
        self.assertEqual(res["status"], "partial")

    def test_discovery_from_case_folder(self):
        os.makedirs(self.path("in", "sub"))
        shutil.copy(self.write("m.md", MD), self.path("in", "sub", "thesis.md"))
        self.write("in/sub/zotero.bib", "@article{a, author={A, A.}, title={T a}, journal={J}, year=2000}\n")
        self.write("in/task.md", "# task\n")
        case = self.write("in/case.json", json.dumps({"case_id": "c1", "materials": {"draft": "sub/thesis.md", "bib": ["sub/zotero.bib"]}, "output_contract": ["status"]}))
        work = self.path("w")
        code, t = run("prepare", "--case", case, "--work", work)
        self.assertEqual(code, 0, t)
        self.assertIn("manuscript: thesis.md | libraries: zotero.bib", t)

    def test_damaged_library_is_skipped_not_fatal(self):
        bad = self.write("bad.json", '[["not", "csl"], {"title": 1}]')
        ms = self.write("m.md", "Claim [1].\n\n## References\n\n[1] Aaa, A. (2001). First work. Journal One, 1(1), 1-10.\n")
        code, t = run("prepare", ms, "--work", self.path("w"), "--lib", bad)
        self.assertEqual(code, 0, t)
        self.assertIn("WARNING: library file bad.json could not be parsed", t)

    def test_contract_fields(self):
        ms = self.write("m.md", MD)
        case = self.write("case.json", json.dumps({"case_id": "demo-1", "output_contract": {"fields": ["case_id", "目标产物", "事实与来源映射", "版本与边界", "reviewer_score"]}}))
        work = self.path("w")
        run("prepare", ms, "--work", work)
        code, t = run("build", work, "--out", self.path("out"), "--case", case)
        res = json.load(open(self.path("out", "result.json")))
        self.assertEqual(res["case_id"], "demo-1")
        self.assertEqual(res["reviewer_score"], None)
        self.assertEqual(res["_meta"]["unfilled_fields"], ["reviewer_score"])
        self.assertEqual(code, 2)
        self.assertIn("citations", res["事实与来源映射"])
        self.assertIn("changes", res["版本与边界"])
        ans = self.write("ans.json", json.dumps({"reviewer_score": "n/a: set by the platform"}))
        code, t = run("build", work, "--out", self.path("out"), "--case", case, "--answers", ans)
        self.assertEqual(code, 0)

    def test_no_reference_list_uses_library_order(self):
        lib = self.write("lib.bib", "@article{a, author={A, A.}, title={T a}, journal={J}, year=2000}\n@article{b, author={B, B.}, title={T b}, journal={J}, year=2001}\n")
        ms = self.write("m.md", "Claim [2]. Other [1].\n")
        work, out, _ = self.build(ms, "--lib", lib)
        res = json.load(open(os.path.join(out, "result.json")))
        self.assertTrue(any(u["kind"] == "assumption" for u in res["uncertainty"]))
        text = open(os.path.join(out, "manuscript.md"), encoding="utf-8").read()
        self.assertIn("Claim [1]. Other [2].", text)
        self.assertIn("## References", text)

    def test_author_year_unchanged_when_consistent(self):
        ms = self.write("m.md", "Alpha (Aaa, 2001). Beta (Bbb & Ccc, 2002).\n\n## References\n\nAaa, A. (2001). Title one. Journal, 1(1), 1-10.\nBbb, B., & Ccc, C. (2002). Title two. Journal, 2(1), 1-10.\n")
        work, out, _ = self.build(ms)
        self.assertIn("Alpha (Aaa, 2001). Beta (Bbb & Ccc, 2002).", open(os.path.join(out, "manuscript.md"), encoding="utf-8").read())

    def test_run_one_shot(self):
        ms = self.write("m.md", MD)
        code, t = run("run", ms, "--out", self.path("o"), "--work", self.path("w"))
        self.assertIn("--- build", t)
        self.assertTrue(os.path.isfile(self.path("o", "result.json")))

    def test_convert(self):
        lib = self.write("l.bib", "@article{a, author={Doe, Jane}, title={T a}, journal={J}, year=2000, volume={1}, pages={1--2}}\n")
        out = self.path("o.txt")
        run("convert", "--lib", lib, "--style", "gbt7714", "--out", out)
        self.assertIn("DOE J. T a[J]. J, 2000, 1: 1-2.", open(out, encoding="utf-8").read())


# ------------------------------------------------------------------------------------------------ generated manuscripts: invariants
class TestGenerated(TmpCase):
    """random manuscripts with shuffled lists, ranges, gaps, unresolved and uncited entries; after a build every marker must still denote the same work,
    numbers must be 1..N in order of first appearance, and a second build must change nothing"""
    TOPICS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "sigma"]

    def make(self, rng):
        n = rng.randint(4, 12)
        works = ["Study of %s %s transport" % (rng.choice(self.TOPICS), self.TOPICS[i % len(self.TOPICS)]) for i in range(n)]
        order = list(range(n))
        rng.shuffle(order)  # list order = shuffled
        lines = ["[%d] Author%s, A. (%d). %s. Journal %d, %d(1), %d-%d." % (pos + 1, chr(65 + w), 1990 + w, works[w], w, w + 1, w * 10 + 1, w * 10 + 9) for pos, w in enumerate(order)]
        pos_of = {w: pos + 1 for pos, w in enumerate(order)}
        sents, cited_works = [], []
        for _ in range(rng.randint(5, 14)):
            k = rng.choice([0, 1, 1, 2, 3, 4])
            ws = rng.sample(range(n), min(k, n))
            nums = sorted(pos_of[w] for w in ws)
            cited_works.append(ws)
            if not nums:
                sents.append("Plain statement number %d." % len(sents))
            else:
                marker = "[%s]" % ", ".join(map(str, nums)) if rng.random() < 0.5 else "[%s]" % ",".join(map(str, nums))
                sents.append("Claim %d is stated %s." % (len(sents), marker))
        text = "# Title\n\n## Body\n\n" + " ".join(sents) + "\n\n## References\n\n" + "\n".join(lines) + "\n"
        return text, works, cited_works

    def test_audit_matches_ground_truth(self):
        """seeded defects: out-of-range numbers (unresolved), uncited entries, unsorted / uncompressed markers; the audit must report exactly the seeded ones"""
        rng = random.Random(11)
        for k in range(40):
            text, works, cited = self.make(rng)
            body, _, refs = text.partition("## References")
            n_list = len(re.findall(r"^\[\d+\]", refs, re.M))
            bad_nums = 0
            def corrupt(m):
                nonlocal bad_nums
                if rng.random() < 0.15:
                    bad_nums += 1
                    return "[%d]" % (n_list + rng.randint(1, 5))
                return m.group(0)
            body2 = re.sub(r"\[(\d+)\](?=\.)", corrupt, body)
            text2 = body2 + "## References" + refs
            ms = self.write("a%d.md" % k, text2)
            work = self.path("aw%d" % k)
            run("prepare", ms, "--work", work)
            L = json.load(open(os.path.join(work, "ledger.json")))
            iss = cl.run_audit(json.load(open(os.path.join(work, "doc.json"))), L)
            unresolved = sum(1 for i in iss if i["kind"] == "unresolved_citation")
            cited_nums = {n for m in re.finditer(r"\[([^\]]*)\]", body2) for n in cite.expand(m.group(1)) if n <= n_list}
            uncited = sum(1 for i in iss if i["kind"] == "uncited_reference")
            self.assertEqual(unresolved, bad_nums, "case %d unresolved" % k)
            self.assertEqual(uncited, n_list - len(cited_nums), "case %d uncited" % k)

    def titles(self, text, with_marks=True):
        body, _, refs = text.partition("## References")
        lst = {int(m.group(1)): re.search(r"\(\d+\)\. (.*?)\. \*?Journal", m.group(2)).group(1) for m in re.finditer(r"^\[(\d+)\] (.*)$", refs, re.M)}
        out = []
        for m in re.finditer(r"Claim (\d+) is stated \[([^\]]*)\]", body):
            nums = cite.expand(m.group(2))
            out.append((int(m.group(1)), sorted(lst[n] for n in nums)))
        return out, lst

    def test_invariants(self):
        rng = random.Random(7)
        for k in range(40):
            text, works, cited = self.make(rng)
            ms = self.write("g%d.md" % k, text)
            work, out = self.path("w%d" % k), self.path("o%d" % k)
            run("prepare", ms, "--work", work)
            code, _ = run("build", work, "--out", out)
            new = open(os.path.join(out, "manuscript.md"), encoding="utf-8").read()
            before, _ = self.titles(text)
            after, lst = self.titles(new)
            self.assertEqual(before, after, "case %d: markers changed meaning" % k)
            self.assertEqual(sorted(lst), list(range(1, len(lst) + 1)), "case %d numbering" % k)
            nums_in_text = []
            for m in re.finditer(r"\[([^\]]*)\]", new.split("## References")[0]):
                for n in cite.expand(m.group(1)):
                    if n not in nums_in_text:
                        nums_in_text.append(n)
            self.assertEqual(nums_in_text, list(range(1, len(nums_in_text) + 1)), "case %d first-appearance order" % k)
            self.assertEqual(len(lst), len(nums_in_text), "case %d list vs cited" % k)
            w2, o2 = self.path("v%d" % k), self.path("p%d" % k)
            run("prepare", os.path.join(out, "manuscript.md"), "--work", w2)
            run("build", w2, "--out", o2)
            self.assertEqual(new, open(os.path.join(o2, "manuscript.md"), encoding="utf-8").read(), "case %d not idempotent" % k)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", action="store_true")
    a, rest = ap.parse_known_args()
    unittest.main(warnings="ignore", argv=[sys.argv[0]] + (["-v"] if a.v else []) + rest)
