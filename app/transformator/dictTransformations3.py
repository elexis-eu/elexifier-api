# coding=Windows-1250
#import xml.etree, xml.etree.ElementTree
from lxml import etree
import copy, re, logging, traceback, zipfile, json, pathlib, eventlet, sys, datetime, os, os.path, io, time
from eventlet import wsgi
urllib_parse = eventlet.import_patched("urllib.parse")
urllib_request = eventlet.import_patched("urllib.request")
urllib_error = eventlet.import_patched("urllib.error")

Verbose = False
Verbose2 = False

class TXpathSelector:
    __slots__ = ["expr"]
    def __init__(self, expr):
        self.expr = expr
    def findall(self, tree):
        #print("tree = %s, expr = %s" % (tree, self.expr))
        #if type(tree) is not TMyElement: tree = tree.getroot()
        for x in tree.findall(self.expr): yield x
    def ToJson(self): return { "type": "xpath", "expr": self.expr }
class TUnionSelector:
    __slots__ = ["selectors"]
    def __init__(self, selectors):
        self.selectors = selectors
    def findall(self, tree):
        seen = set()
        for sel in self.selectors:
            for x in sel.findall(tree):
                xid = id(x)
                if xid in seen: continue
                seen.add(xid); yield x
    def ToJson(self): return { "type": "union", "selectors": [sel.ToJson() for sel in self.selectors] }
class TExcludeSelector:
    __slots__ = ["left", "right"] # represents left - right
    def __init__(self, left, right):
        self.left = left
        self.right = right
    def findall(self, tree):    
        toExclude = set(id(x) for x in self.right.findall(tree))
        for x in self.left.findall(tree):
            if id(x) in toExclude: continue
            yield x
    def ToJson(self): return { "type": "exclude", "left": self.left.ToJson(), "right": self.left.ToJson() }

def JsonToSelector(json):
    if not json: return None
    ty = json.get("type", None)
    if ty == "xpath": return TXpathSelector(json["expr"])
    elif ty == "union": return TUnionSelector([JsonToSelector(x) for x in json["selectors"]])
    elif ty == "exclude": return TExcludeSelector(JsonToSelector(json["left"]), JsonToSelector(json["right"]))
    assert False, "JsonToSelector: unknown type %s" % repr(ty)

def GetInnerText(elt, recurse):
    if elt is None: return ""
    L = []
    if elt.text: L.append(elt.text)
    n = len(elt)
    for i in range(n):
        child = elt[i]
        if recurse: L.append(GetInnerText(child, recurse))
        if child.tail: L.append(child.tail)
    return "".join(L)

def AppendToText(node, what):
    if node is None: return
    if what is None or what == "": return
    if node.text is None: node.text = what
    else: node.text += what

def AppendToTail(node, what):
    if node is None: return
    if what is None or what == "": return
    if node.tail is None: node.tail = what
    else: node.tail += what

class TTransformOrder:
    __slots__ = ["elt", "rexMatch", "rexGroup", "attr", "attrVal", "matchedStr", "msFrom", "msTo", "trLanguage", "finalStr"]
    # msFrom and msTo may point to milestone elements, if a regular expression
    # was used on the inner text (possibly recursive).
    def __init__(self, elt, rexMatch, rexGroup, attr, attrVal, matchedStr, finalStr):
        self.elt = elt; self.rexMatch = rexMatch
        self.rexGroup = rexGroup; self.attr = attr
        self.attrVal = attrVal; self.matchedStr = matchedStr; self.finalStr = finalStr
        #print("TO %s -> %s" % (self.matchedStr, self.finalStr))
        self.msFrom = None; self.msTo = None; self.trLanguage = None
    def RemoveMilestones(self):
        def Remove(ms):
            parent = ms.getparent()
            idx = parent.index(ms)
            textBefore = parent.text if idx == 0 else parent[idx - 1].tail
            textAfter = ms.tail
            if (not textBefore) and (not textAfter): s = None
            else: s = ("" if textBefore is None else textBefore) + ("" if textAfter is None else textAfter)
            if idx > 0: parent[idx - 1].tail = s
            else: parent.text = s
            parent.remove(ms)
        for ms in self.msFrom or []: Remove(ms)
        for ms in self.msTo or []: Remove(ms)
    def InsertMilestones(self, mapper, root):
        self.msFrom = None; self.msTo = None
        if not self.rexMatch: return
        if self.attr != ATTR_INNER_TEXT and self.attr != ATTR_INNER_TEXT_REC: return
        recurse = (self.attr == ATTR_INNER_TEXT_REC)
        startIdx = self.rexMatch.start(self.rexGroup)
        endIdx = self.rexMatch.end(self.rexGroup)
        if startIdx < 0 or endIdx < 0: return
        if self.matchedStr == self.attrVal: return # the whole string was matched
        if startIdx == 0 and endIdx == len(self.attrVal): return # should be covered by the previous case
        # We should insert two milestones so that the text from <elt> to the first
        # milestone is startIdx characters long and the text from the first to the second
        # milestone is endIdx - startIdx characters long.  The problem with this is that there
        # may be several possible positions for a milestone:
        #    <elt>foo<a><b>bar</b>baz</a>quux</elt>
        # startIdx = 3 would allow us to place the milestone in any of the following positions:
        #    <elt>foo<milestone/><a><b>bar</b>baz</a>quux</elt>
        #    <elt>foo<a><milestone/><b>bar</b>baz</a>quux</elt>
        #    <elt>foo<a><b><milestone/>bar</b>baz</a>quux</elt>
        # The same ambiguity might occur with the endIdx.  It's hard to choose in advance
        # which of these possible placements to use.  For example, suppose we have
        # startIdx = 2 and endIdx = 4 in the following element:
        #    <elt>xx<a>y</a><b>y</b>zz</elt>
        # In this case it makes sense to put the starting milestone early and the ending milestone
        # late so that eventually a new element can be inserted without splitting any existing ones:
        #    <elt>xx<milestone start/><a>y</a><b>y</b><milestone end/>zz</elt>
        # But on the other hand, if we had started with the following:
        #    <elt>xx<a>y<b>y</b></a>zz</elt>   startIdx = 2, endIdx = 4
        # with the following possible placements of the milestones:
        #    <elt>xx<start?/><a><start?/>y<b>y<end?/></b><end?/></a><end?/>zz</elt>
        # it makes sense to choose the latest start and the second of three possible ends:
        #    <elt>xx<a><milestone start/>y<b>y</b><milestone end/></a>zz</elt>
        # In general, then, we should insert all the milestones we can and allow
        # a later stage of the algorithm to choose a combination of the starting and ending
        # milestone that will allow a new element to be introduced with the least amount of disruption.
        # - If startIdx == endIdx, we'll just insert starting milestones to simplify matters.
        curPos = 0; self.msFrom = []; self.msTo = [] if endIdx > startIdx else None
        def MakeMs(isStart, tail_):
            ms = mapper.E(ELT_MILESTONE, text = None, tail = tail_)
            ms.transformOrder = self; ms.isStart = isStart
            if isStart: self.msFrom.append(ms)
            else: self.msTo.append(ms)
            return ms
        def Rec(e):
            nonlocal curPos, recurse
            i = 0; nChildren = len(e)
            while i <= nChildren:
                assert nChildren == len(e)
                # See if any milestones need to be inserted between the end of child i - 1
                # and the start of child i.  (For i = 0, this is the space between the start-tag
                # of 'e' and the start of child 0; for i == nChildren, this is the space between
                # the end of the last child and the end-tag of 'e'.)
                s = e.text if i == 0 else e[i - 1].tail
                if s == None: s = ""
                nextPos = curPos + len(s)
                if False: print("InsertMilestones, e = %s, child %d/%d s = %s, curPos = %d, nextPos = %d, recurse = %s" % (e.tag, i, nChildren, s, curPos, nextPos, recurse))
                if curPos <= startIdx < endIdx <= nextPos:
                    #print("Inserting ms at %d and me at %d into %s" % (startIdx - curPos, endIdx - curPos, e))
                    msS = MakeMs(True, None if startIdx == endIdx else s[startIdx - curPos:endIdx - curPos])
                    msE = MakeMs(False, None if endIdx == nextPos else s[endIdx - curPos:])
                    preS = None if curPos == startIdx else s[:startIdx - curPos]
                    if i == 0: e.text = preS
                    else: e[i - 1].tail = preS
                    e.insert(i, msE); e.insert(i, msS); nChildren += 2; i += 2
                elif curPos <= startIdx <= nextPos:    
                    #print("Inserting ms at %d into %s" % (startIdx - curPos, e))
                    msS = MakeMs(True, None if startIdx == nextPos else s[startIdx - curPos:])
                    preS = None if curPos == startIdx else s[:startIdx - curPos]
                    if i == 0: e.text = preS
                    else: e[i - 1].tail = preS
                    e.insert(i, msS); nChildren += 1; i += 1
                elif curPos <= endIdx <= nextPos:
                    #print("Inserting me at %d into %s" % (endIdx - curPos, e))
                    msE = MakeMs(False, None if endIdx == nextPos else s[endIdx - curPos:])
                    preS = None if curPos == endIdx else s[:endIdx - curPos]
                    if i == 0: e.text = preS
                    else: e[i - 1].tail = preS
                    e.insert(i, msE); nChildren += 1; i += 1
                curPos = nextPos    
                # Process the child i recursively.
                if i < nChildren and recurse: Rec(e[i])
                i += 1
        assert self.attrVal == GetInnerText(self.elt, recurse)
        oldInnerText = GetInnerText(root, True)
        Rec(root)
        #assert self.attrVal == GetInnerText(self.elt, recurse)
        newInnerText = GetInnerText(root, True)
        assert oldInnerText == newInnerText # inserting milestones should not change anything else
        print("TransformOrder for <%s>, rex %s, matched %s -> %s, inserted %d start and %d end milestones." % (
            self.elt.tag, self.rexMatch.re.pattern, repr(self.matchedStr), repr(self.finalStr), 
            len(self.msFrom), -1 if self.msTo is None else len(self.msTo)))

class TSimpleTransformer:
    # This transformer calls 'selector' to select the nodes; from each
    # of those nodes, it takes the attribute 'attr'; searches for the
    # first occurrence of the regular expression 'reg' in it; and returns
    # the group 'rexGroup' from the resulting match.
    __slots__ = ["selector", "attr", "rex", "crex", "rexGroup", "constValue", "xlat"]
    def __init__(self, selector, attr, rex = "", rexGroup = None, constValue = None, xlat = None):
        self.selector = selector
        self.attr = attr
        self.rex = rex
        self.crex = None if not rex else re.compile(rex)
        self.rexGroup = rexGroup
        self.constValue = constValue
        self.xlat = xlat
    def Xlat(self, s):
        if not self.xlat: return s
        else: 
            #print("XLAT %s  %s -> %s" % (self.xlat, s, self.xlat.get(s, s)))
            return self.xlat.get(s, s)
    def findall(self, root): # yields (Element, str) pairs
        for elt in self.selector.findall(root):
            if self.attr == ATTR_INNER_TEXT: attrVal = GetInnerText(elt, False)
            elif self.attr == ATTR_INNER_TEXT_REC: attrVal = GetInnerText(elt, True)
            elif self.attr == ATTR_CONSTANT: attrVal = self.constValue
            else: attrVal = elt.get(self.attr, None)
            if attrVal is None: continue
            if not self.rex: yield TTransformOrder(elt, None, None, self.attr, attrVal, attrVal, self.Xlat(attrVal)); continue
            m = self.crex.search(attrVal)
            if not m: continue
            s = ""
            try: s = m.group(0 if self.rexGroup is None else self.rexGroup)
            except: pass # must be an error in the mapping, perhaps an invalid group name
            yield TTransformOrder(elt, m, self.rexGroup, self.attr, attrVal, s, self.Xlat(s))
    def ToJson(self): 
        h = {"type": "simple", "selector": self.selector.ToJson(), "attr": self.attr}
        if self.rex is not None: h["rex"] = self.rex
        if self.rexGroup is not None: h["rexGroup"] = self.rexGroup
        if self.constValue is not None: h["const"] = self.constValue
        if self.xlat is not None: h["xlat"] = {x: self.xlat[x] for x in self.xlat}
        return h
class TUnionTransformer:
    __slots__ = ["transformers"] # list ot TSimpleTransformer's
    def __init__(self, transformers):
        self.transformers = transformers
    def findall(self, root):
        seen = set()
        for sel in self.transformers:
            for trOrder in sel.findall():
                eid = id(trOrder.elt)
                if eid in seen: continue
                seen.add(eid)
                yield trOrder
    def ToJson(self):
        return {"type": "union", "transformers": [tr.ToJson() for tr in self.transformers]}

def JsonToTransformer(json):
    if not json: return None
    ty = json.get("type", None)
    if ty == "simple": return TSimpleTransformer(
        JsonToSelector(json["selector"]), json["attr"],
        json.get("rex", None), json.get("regGroup", None), json.get("const", None),
        json.get("xlat", None))
    elif ty == "union": return TUnionTransformer([JsonToTransformer(x) for x in json["transformers"]])
    assert False, "JsonToTransformer: unknown type %s" % repr(ty)

# pseudo-attribute names
NS_ATTR = "http://elex.is/wp1/teiLex0Mapper/legacyAttributes"
NS_META = "http://elex.is/wp1/teiLex0Mapper/meta"
NS_TEI = "http://www.tei-c.org/ns/1.0"
NS_XML = "http://www.w3.org/XML/1998/namespace"
NS_MAP = {"m": NS_META, "a": NS_ATTR, None: NS_TEI, "xml": NS_XML}
ATTR_INNER_TEXT = "{%s}innerText" % NS_META
ATTR_INNER_TEXT_REC = "{%s}innerTextRec" % NS_META
ATTR_CONSTANT = "{%s}constant" % NS_META
ATTR_ID = "{%s}id" % NS_XML
ATTR_LEGACY_ELT = "{%s}e" % NS_META
ATTR_LEGACY_ID = "{%s}id" % NS_META
ATTR_LEGACY_SRC = "{%s}s" % NS_META
ATTR_XML_LANG = "{%s}lang" % NS_XML
ATTR_TEMP_type = "{%s}type" % NS_META
ATTR_type_UNPREFIXED = "type"
#ATTR_type = "{%s}%s" % (NS_TEI, ATTR_type_UNPREFIXED)
ATTR_MATCH = "{%s}match" % NS_META
ATTR_MATCH_ATTR = "{%s}matchAttr" % NS_META
ATTR_MATCH_FROM = "{%s}matchFrom" % NS_META
ATTR_MATCH_TO = "{%s}matchTo" % NS_META
ELT_ENTRY_PLACEHOLDER = "{%s}entryPlaceholder" % NS_META
ELT_MILESTONE = "{%s}milestone" % NS_META
ELT_TEMP_ROOT = "{%s}tempRoot" % NS_META
#ELT_PHASE_2_STUB = "{%s}phase2Stub" % NS_META
ELT_dictScrap = "{%s}dictScrap" % NS_TEI
ELT_seg = "{%s}seg" % NS_TEI
ELT_orth = "{%s}orth" % NS_TEI
ELT_form = "{%s}form" % NS_TEI
ELT_cit = "{%s}cit" % NS_TEI
ELT_quote = "{%s}quote" % NS_TEI
ELT_sense = "{%s}sense" % NS_TEI
ELT_gram = "{%s}gram" % NS_TEI
ELT_gramGrp = "{%s}gramGrp" % NS_TEI
ELT_def = "{%s}def" % NS_TEI
ELT_body = "{%s}body" % NS_TEI
ELT_text = "{%s}text" % NS_TEI
ELT_tei = "{%s}TEI" % NS_TEI
# teiHeader and its descendants
ELT_teiHeader = "{%s}teiHeader" % NS_TEI
ELT_titleStmt = "{%s}titleStmt" % NS_TEI
ELT_title = "{%s}title" % NS_TEI
ELT_publicationStmt = "{%s}publicationStmt" % NS_TEI
ELT_p = "{%s}p" % NS_TEI
ELT_publisher = "{%s}publisher" % NS_TEI
ELT_bibl = "{%s}bibl" % NS_TEI
ELT_sourceDesc = "{%s}sourceDesc" % NS_TEI
ELT_fileDesc = "{%s}fileDesc" % NS_TEI
ELT_entry = "{%s}entry" % NS_TEI
ELT_author = "{%s}author" % NS_TEI
ELT_respStmt = "{%s}respStmt" % NS_TEI
ELT_resp = "{%s}resp" % NS_TEI
ELT_name = "{%s}name" % NS_TEI
ELT_extent = "{%s}extent" % NS_TEI
ELT_availability = "{%s}availability" % NS_TEI
ELT_licence = "{%s}licence" % NS_TEI
ELT_date = "{%s}date" % NS_TEI
#ATTR_when  = "{%s}when" % NS_TEI
ATTR_when_UNPREFIXED = "when"
ELT_idno = "{%s}idno" % NS_TEI
CommentType = type(etree.Comment(""))

MATCH_entry = "entry"
MATCH_entry_lang = "entry_lang"
MATCH_hw = "hw"
MATCH_lemma = "lemma"
MATCH_sense = "sense"
MATCH_def = "def"
MATCH_pos = "pos"
MATCH_hw_tr = "hw_tr"
MATCH_hw_tr_lang = "hw_tr_lang"
MATCH_ex = "ex"
MATCH_ex_tr = "ex_tr"
MATCH_ex_tr_lang = "ex_tr_lang"

class TMapping:
    #
    __slots__ = [
        "selEntry",      # becomes <entry>
        # - The rest is relative to the entry.
        "xfHw",  # headword; becomes <form type="lemma"><orth>
        "xfLemma",  # headword; becomes <form type="simple"><orth>
        "selSense",  # becomes <sense>  
        "xfEntryLang", # becomes @xml:lang of <entry>
        "xfDef",  # definition; becomes <def>
        "xfPos",  # part-of-speech; becomes <gram type="pos">
        "xfHwTr", # translated headword; becomes <cit type="translationEquivalent">
        "xfHwTrLang",  # language of the translated headword [goes into the xml:lang attribute]
        "xfEx", # example; becomes <cit type="example"><quote>
        "xfExTr", # translated example; becomes <cit type="translation">
        "xfExTrLang",  # language of the translated example [goes into the xml:lang attribute]
    ]
    def __init__(self, js = None):
        self.selEntry = None; self.xfEntryLang = None
        self.xfHw = None; self.xfLemma = None; self.selSense = None
        self.xfPos = None; self.xfHwTr = None; self.xfHwTrLang = None
        self.xfEx = None; self.xfExTr = None; self.xfExTrLang = None
        self.xfDef = None
        if js: self.InitFromJson(js)
    def ToJson(self):
        h = {}
        def _(key, val):
            if val: h[key] = val.ToJson()
        _("entry", self.selEntry)
        _("sense", self.selSense)
        _("entry_lang", self.xfEntryLang)
        _("pos", self.xfPos)
        _("hw", self.xfHw)
        _("sec_hw", self.xfLemma)
        _("hw_tr", self.xfHwTr)
        _("hw_tr_lang", self.xfHwTrLang)
        _("ex", self.xfEx)
        _("ex_tr", self.xfExTr)
        _("ex_tr_lang", self.xfExTrLang)
        _("def", self.xfDef)
        return h
    def InitFromJson(self, h):
        self.selEntry = JsonToSelector(h.get("entry", None))
        self.selSense = JsonToSelector(h.get("sense", None))
        self.xfDef = JsonToTransformer(h.get("def", None))
        self.xfPos = JsonToTransformer(h.get("pos", None))
        self.xfHw = JsonToTransformer(h.get("hw", None))
        self.xfLemma = JsonToTransformer(h.get("sec_hw", None))
        self.xfHwTr = JsonToTransformer(h.get("hw_tr", None))
        self.xfHwTrLang = JsonToTransformer(h.get("hw_tr_lang", None))
        self.xfEx = JsonToTransformer(h.get("ex", None))
        self.xfExTr = JsonToTransformer(h.get("ex_tr", None))
        self.xfExTrLang = JsonToTransformer(h.get("ex_tr_lang", None))
        self.xfEntryLang = JsonToTransformer(h.get("entry_lang", None))

def GetMldsMapping():
    m = TMapping()
    m.selEntry = TUnionSelector([
        TXpathSelector("Entry"), TXpathSelector(".//DictionaryEntry")])
    m.xfEntryLang = TSimpleTransformer(
        TXpathSelector("Dictionary"), "sourceLanguage")
    m.xfHw = TSimpleTransformer(TXpathSelector(".//Headword"), ATTR_INNER_TEXT)
    m.selSense = TXpathSelector(".//SenseGrp")    
    m.xfDef = TSimpleTransformer(TXpathSelector(".//Definition"), ATTR_INNER_TEXT)
    m.xfPos = TSimpleTransformer(TXpathSelector(".//PartOfSpeech"), "value")
    m.xfHwTr = TSimpleTransformer(
        TExcludeSelector(
            TXpathSelector(".//Translation"),
            TXpathSelector(".//ExampleCtn//Translation")),
        ATTR_INNER_TEXT)
    m.xfHwTrLang = TSimpleTransformer(TXpathSelector(".//Locale"), "lang")
    m.xfEx = TSimpleTransformer(TXpathSelector(".//Example"), ATTR_INNER_TEXT)
    m.xfExTr = TSimpleTransformer(TXpathSelector(".//ExampleCtn//Translation"), ATTR_INNER_TEXT)
    m.xfExTrLang = TSimpleTransformer(TXpathSelector(".//ExampleCtn//Locale"), "lang")
    return m

def GetSldMapping():
    m = TMapping()
    m.selEntry = TXpathSelector(".//geslo")
    m.xfEntryLang = TSimpleTransformer(TXpathSelector(".//geslo"),
        ATTR_CONSTANT, constValue = "sl")
    m.xfHw = TSimpleTransformer(TXpathSelector(".//iztocnica"), ATTR_INNER_TEXT)
    m.selSense = TUnionSelector([
        TXpathSelector(".//pomen"), TXpathSelector(".//podpomen")])
    m.xfDef = TSimpleTransformer(
        TExcludeSelector(
            TXpathSelector(".//indikator"),
            TUnionSelector([
                TXpathSelector(".//stalna_zveza//indikator"),
                TXpathSelector(".//frazeoloska_enota//indikator")])), ATTR_INNER_TEXT)
    m.xfPos = TSimpleTransformer(TXpathSelector(".//besedna_vrsta"), ATTR_INNER_TEXT)
    m.xfHwTr = None
    m.xfHwTrLang = None
    m.xfEx = TSimpleTransformer(TXpathSelector(".//zgled"), ATTR_INNER_TEXT_REC)
    m.xfExTr = None
    m.xfExTrLang = None
    return m

def GetAnwMapping():
    m = TMapping()
    m.selEntry = TXpathSelector(".//artikel")
    m.xfEntryLang = TSimpleTransformer(TXpathSelector(".//artikel"),
        ATTR_CONSTANT, constValue = "nl")
    m.xfHw = TSimpleTransformer(TXpathSelector(".//Lemmavorm"), ATTR_INNER_TEXT_REC)
    m.selSense = TXpathSelector(".//Kernbetekenis")
    m.xfDef = TSimpleTransformer(TXpathSelector(".//Definitie"), ATTR_INNER_TEXT_REC)
    m.xfPos = TSimpleTransformer(TXpathSelector(".//Woordsoort/Type"), ATTR_INNER_TEXT,
        xlat = {"substantief": "noun"})
    m.xfHwTr = None
    m.xfHwTrLang = None
    m.xfEx = TSimpleTransformer(TXpathSelector(".//Voorbeeld/Tekst"), ATTR_INNER_TEXT_REC)
    m.xfExTr = None
    m.xfExTrLang = None
    return m

def GetDdoMapping():
    m = TMapping()
    m.selEntry = TXpathSelector(".//Artikel")
    m.xfEntryLang = TSimpleTransformer(TXpathSelector(".//Artikel"),
        ATTR_CONSTANT, constValue = "da")
    m.xfHw = TSimpleTransformer(TXpathSelector(".//Holem"), ATTR_INNER_TEXT)
    m.selSense = TUnionSelector([
        TXpathSelector(".//Semem"),
        TXpathSelector(".//Subsem")])
    m.xfDef = TSimpleTransformer(TXpathSelector(".//Denbet"), ATTR_INNER_TEXT)
    m.xfPos = TSimpleTransformer(TXpathSelector(".//Lemklas"), ATTR_INNER_TEXT)
    m.xfHwTr = None
    m.xfHwTrLang = None
    m.xfEx = TSimpleTransformer(TXpathSelector(".//Citat/txt"), ATTR_INNER_TEXT_REC)
    m.xfExTr = None
    m.xfExTrLang = None
    return m

def GetToyMapping():
    m = TMapping()
    m.selEntry = TXpathSelector(".//Entry")
    #m.xfDef = TSimpleTransformer(TXpathSelector(".//Headword"), ATTR_INNER_TEXT_REC, "x(?P<tralala>[^x]*)x", "tralala")
    m.xfDef = TSimpleTransformer(TXpathSelector(".//Def"), ATTR_INNER_TEXT_REC)
    m.xfHw = TSimpleTransformer(TXpathSelector(".//Headword"), ATTR_INNER_TEXT_REC)
    m.selSense = TXpathSelector(".//Sense")
    return m

def GetMcCraeTestMapping():
    m = TMapping()
    m.selEntry = TXpathSelector(".//LexicalEntry")
    m.xfEntryLang = TSimpleTransformer(TXpathSelector(".//LexicalEntry"), ATTR_CONSTANT, constValue = "en")
    m.xfHw = TSimpleTransformer(TXpathSelector(".//Sense"), "n")
    m.xfDef = TSimpleTransformer(TXpathSelector(".//Sense"), "synset")
    m.selSense = TXpathSelector(".//Sense")
    #m.xfEntryLang = TSimpleTransformer(TXpathSelector(".//LexicalEntry"), ATTR_CONSTANT, constValue = "en")
    #m.xfEntryLang = None; m.xfHwTr = None; m.xfEx = None; m.xfExTr = None; m.xfExTrLang = None; m.selSense = None
    return m

def GetSpMapping():
    js = {"entry": {"type": "xpath", "expr": ".//geslo"},
          "hw": {"type": "simple", "selector": {"type": "xpath", "expr": ".//ge"},
               "attr": "{http://elex.is/wp1/teiLex0Mapper/meta}innerTextRec"},
          "sense": {"type": "xpath", "expr": "dummy" } }
    m = TMapping()
    m.InitFromJson(js)
    return m

class TMyElement(etree.ElementBase):
    def IsAncestorOf(self, other):
        return self.entryTime <= other.entryTime and other.exitTime <= self.exitTime
    def IsDescendantOf(self, other):
        return other.entryTime <= self.entryTime and self.exitTime <= other.exitTime

# This assumes that the form/orth pair is represented by orth, gramGrp/gram by gram, cit/quote by cit.
# Also note that this hash table is used in stage 2, when <orth> elements are still
# actually temporary <orthHw> and <orthLemma> - they will be renamed in stage 3.
allowedParentHash = {
    ELT_seg: set([ELT_seg, ELT_entry, ELT_orth, ELT_def, ELT_gram, ELT_cit, ELT_dictScrap, ELT_sense]),
    ELT_def: set([ELT_sense, ELT_dictScrap, ELT_entry]),
    ELT_orth: set([ELT_sense, ELT_dictScrap, ELT_entry]),
    ELT_gram: set([ELT_sense, ELT_dictScrap, ELT_entry]),
    ELT_cit: set([ELT_sense, ELT_dictScrap, ELT_entry, ELT_cit]),
    ELT_sense: set([ELT_sense, ELT_dictScrap, ELT_entry]),
    ELT_entry: set([ELT_entry]),
    ELT_ENTRY_PLACEHOLDER: set([ELT_entry]),
    ELT_dictScrap: set([ELT_entry, ELT_dictScrap])
}

# To map an individual entry:
# (1) Go bottom-up and transform all nodes that have to be transformed, segify the rest.
# These transformations can produce the following tags, which may contain the following: 
#    seg                                       -> CDATA, seg
#    form/orth, def, gramGrp/gram, cit/quote   -> CDATA, seg, cit
#    sense                                     -> CDATA, seg, cit, sense, form, gramGrp, def  
#    dictScrap                                 -> CDATA  seg  cit  sense  form  gramGrp  def  
#    entry                                     ->             cit  sense  form, gramGrp      dictScrap entry 
# (2) Some of the problems can be fixed by moving a node up.  For example,
# a <sense> inside a <seg> can be moved up; the <seg> can be split into two parts in this process.
# - We probably shouldn't split non-seg things, such as <def>.  So if a <sense>
# appears inside a <def>, it should be moved out of it, so that it becomes the <def>'s sibling.
# - At the end, if our <entry> contains anything that it shouldn't,
# we should wrap those things in <dictScrap>s.
# - At the topmost level, an <entry> may not contain <seg>s, but it may
# contain <dictScraps>, so <seg>s should simply be renamed.
#
# The details of the transformation depend on what the current
# node is being transformed into:
# (1) <seg>
#     If any children are something other than <seg>s, we must split the present node
#     and those children become its siblings.  E.g.
#              <seg a> x1 <seg b/> x2 <sense/> x3 <seg c/> x4 </seg> x5
#     becomes  <seg a> x1 <seg b/> x2 </seg> <sense/> <seg a> x3 <seg c/> x4 </seg> x5
# (2) <form/orth>, <def>, <gramGrp/gram>, <cit/quote>
#     If any children are something other than <seg> or <cit>, we must move them out
#     and turn the former children into siblings.  We shouldn't split the present node.
# (3) <sense>
#     It shouldn't be possible for there to be any children of the wrong type here.
#  
# - If the transformation takes a string from an attribute, make a new element
#   that is a sibling of the element from which the attribute was taken; the latter
#   should be turned into <dictScrap> or <seg>.
# - If the transformation takes a string from the inner text of the element (could be recursive or not):
#   - Before we start any transformations, insert two childless empty milestone elements
#     to mark the beginning and the end of the text range (if a regular expression was used)
#     (unless it covers the whole element).
#   - When, proceeding from the bottom up, we reach this element, check if the
#     text between the milestones (or the complete inner text (possibly recursive) if there
#     are no milestones) still matches what we extracted at the start.
#   - - If it doesn't, simply make a new sibling of our element with the text previously
#       extracted, and convert the current element into a <dictScrap> or <seg>.
#   - - If it does, see if the area between the milestones could be extracted without
#       splitting any elements other than <seg>s.  If yes, extract it and create a new
#       element, while tranforming the old one into a <seg>.  If not, make a new sibling
#       element, as in the previous point.

# We can see from the nesting rules above that a <cit> can be nested directly in a <cit>/<quote>;
# apart from that, <form> <def> <gramGrp> <cit> can only appear directly in a <seg>, <dictScrap> or,
# except <def>, in an <entry>.  
# - Go depth-first from the root <entry>.  When we reach the first node u to be converted
# into something other than a <seg>:
# - - if there are any segs between the root and u, split them, thereby making u a child of the root.
#     If necessary, we can wrap u inside a <dictScrap> after converting it.
# - - While converting u, various descendants might be found in its subtree that, after
#     conversion, cannot remain u's descendants; they will become u's siblings.
#     Can this affect u itself?  No, but some of these new siblings might have to be
#     moved further up the tree.  E.g. if u is a <cit> and its parent is also a <cit>,
#     but one of u's new siblings is a <def>, it needs to be moved further up and not
#     remain u's sibling.
# - - Ideally then, it would be good to 
#
# In general, suppose we have a node A and its descendant B, with everything
# in between to be segified.  If B (or rather, what B is to be converted to)
# can be a child of A, we can simply push it up and split the nodes on the path from A to B.
# Otherwise we should make a copy of B's whole subtree, segify the original, and
# insert the copy as a sibling following A, or even higher up the node if necessary.
# - This process should be done from top to bottom, so that B's tree gets moved
# before it itself gets processed in the same way.
# - This leaves the question of what to do with the transformations that depend on
# a regular expression.  As an example, something like <B> one two three </B>
# would turn into a <seg> one <def> two </def> three </seg>.  Clearly, if this
# <def> is to be taken out, it should be done only in the copied subtree,
# not in the segified original.
# - Thus we have the following algorithm:
# - - Proceed recursively depth-first from top to bottom.  We already know that the root note
#     is to be made an entry, so we can deal with it at the end.
# - - When, during recursion, we find a node B that must be transformed:
# - - Let A be its deepest ancestor that must also be transformed.
# - - If B can be nested directly in A, split any segs in between A and B and
#     promote B into a child of A; then transform it, proceeding recursively through it.
#     - Note that transforming B may involve creating a new node somewhere below B, if a regex is used.
#       This leads to the possibility -- more theoretical than practical -- like this:
#                  <b>   ... <c> ...     foo      ... </c> ... </b>
#        becomes   <seg> ... <c> ... <b> foo </b> ... </c> ... </seg>
#       But suppose now that <c> also needs to be transformed into something.
#       So now it is <c>, not <b>, that is the descendant of <a>.  It can and
#       will eventually be promoted to <a>'s child, but what if it needs to be taken out?
#       Not to mention that, theoretically, <c> itself may use a regex and later be
#       replaced with a new node somewhere even deeper inside the tree.
# - - Otherwise, make a segified copy of B and its subtree, without any transformation
#     orders.  Replace B and its original subtree with the segified copy, and insert
#     B's original subtree as a sibling of A, to be dealt with (transformed and possibly
#     promoted) later.
#
# Idea: make the transformation a two-step process.  In the first step,
# we don't worry about the nesting restrictions.  We simply transform each node
# into one of: seg, orth, def, gram, cit.  We insert new nodes where required due
# to regex usage.  
#   In the second step, we promote descendants and split intervening segs, as needed;
# and where needed, we promote a descendant into a sibling, replacing the original
# descendant with a segified copy.  This means that some things will be split
# more than necessary, since the descendant subtree has already had some of its
# lower parts processed before we got to it.  Or hasn't it?  Important detail: we should make
# the decision to promote a subtree to sibling *before* we go into it to start processing it.
#    def Step2Recursion(curNode, lastNonSegAncestor):
#       if curNode is a <seg>:
#         
#       deferList = []; a' = new node of a suitable type;
#       for each child c of a:
#          (c', deferListC) = Step2Recursion(c)
#          node a = 
#          if c' = null: app
#
# We can simply move around the tree in a sequence, never mind recursion:
#    Let B be the current node, and let P be the node from which we entered B.
#    Thus P is either B's parent or one of its children. 
#    - If P is the last of B's children, move from B into its parent.
#    - Otherwise, if P is any other of B's children, move from B into
#      P's next sibling.
#    - Otherwise we have entered B for the first time.  If B is marked for
#      transformation into a <seg>, it can obviously be a descendant of anything,
#      so we can simply move into it's first child and continue there.
#    - Otherwise, since B won't become a <seg>, there are certain limits to
#      what it can be a child of: it can only be a child of <sense> or <entry>*,
#      or if B is going to be a <cit>, it can also be a child of <cit>
#      [*Note: <def> cannot actually be a child of <entry>, but we can fix that
#      at the end by wrapping it into a <dictScrap>.]
#    - Let A be the nearest ancestor of B that is of a suitable type to be B's parent.
#    - If A is actually B's parent already, we don't have to do anything special
#      and can continue in B's first child.
#    - Otherwise, if there's nothing between B and A but <seg>s, we should
#      split those <seg>s and promote B to become A's child.  Apart from that, 
#      nothing needs to change; we should continue in B's first child.
#    - Otherwise, make a <seg>ified copy of B and its entire subtree; let's
#      call the root of this copy B'.  On the path from B to A, let C be the
#      last node before A, i.e. that ancestor of B which is a child of A.
#      Replace B (and its subtree) with B' (and its subtree) in its current 
#      position in the tree, and insert B (with its subtree) as a child of A
#      immediately after C.  Let the current position in the traversal of the
#      tree be B', and proceed into its first sibling.
class TEntryMapper:
    __slots__ = ["entry", "m", "parser", "mapper",
        "senseIds", 
        "mDef", "mPos", "mHw", "mLemma", "mHwTr", "mHwTrLang", "mEx", "mExTr", "mExTrLang",
        "transformedEntry"]
    def __init__(self, entry, m, parser, mapper):
        self.entry = entry; self.m = m; self.parser = parser; self.mapper = mapper
    def MakeTrOrderHash(self, transformer, augMatchAttr):
        #print("MakeTrOrderHash: entry = %s, tr = %s" % (self.entry, "None" if not transformer else transformer.ToJson()))
        h = {}
        if transformer:
            #print("LOOKING FOR %s" % transformer.ToJson())
            for trOrder in transformer.findall(self.entry): 
                #print("MATCH FOUND! %s" % transformer.ToJson())
                h[id(trOrder.elt)] = trOrder
                SetMatchInfo(trOrder.elt, augMatchAttr, trOrder.attr, trOrder.msFrom, trOrder.msTo)
        return h
    def MakeTrOrderHashFromSelector(self, selector):
        h = {}
        if selector:
            for elt in selector.findall(self.entry): 
                trOrder = TTransformOrder(elt, None, None, None, None, None, None)
                h[id(trOrder.elt)] = trOrder
        return h
    def FindLanguage(self, trOrder, hTrLang):
        # Examine ancestors of trOrder.elt to see which one has a language 
        # transformation order from 'hTrLang', and return that order.
        if not hTrLang: return None
        elt = trOrder.elt
        while not (elt is None):
            tr = hTrLang.get(id(elt), None)
            if tr and not (tr.matchedStr is None): return tr
            elt = elt.getparent()
        print("Warning: no language found for %s" % elt)    
        return None
    def FindLanguageAll(self, hDest, hLang):
        for trDest in hDest.values(): trDest.trLanguage = self.FindLanguage(trDest, hLang)
    def FindSuitableParent(self, elt):
        # Goes up the ancestors of 'elt' until it finds one that can become its parent.
        # Returns this ancestor, plus the next one on the path from that ancestor to 'elt'.
        eltTag = elt.tag; allowedParents = allowedParentHash[eltTag]
        cur = elt; parent = cur.getparent()
        while not (parent is None):
            parentTag = parent.tag
            # Check if this is a suitable parent for 'elt'.
            if parentTag in allowedParents: return (parent, cur)
            # Special case: a <seg> just below the <entry> can and will become a <dictScrap>,
            # so we should accept it as a suitable parent if 'elt' may be a child of a <dictScrap>.
            if parentTag == ELT_seg and parent.getparent() is self.entry and ELT_dictScrap in allowedParents:
                return (parent, cur)
            # Another special case: we will accept the <entry> as a parent of anything,
            # because things that can't actually become its children (e.g. <def>) can always
            # be wrapped in a <dictScrap> later.
            if parentTag == ELT_entry: return (parent, cur)
            # Otherwise move on.
            cur = parent; parent = cur.getparent()
        return (None, None)
    def MakeSegifiedCopy(self, elt):
        def Rec(cur):
            #newCur = self.mapper.Element(ELT_seg)
            cur.tag = ELT_seg
            for i in range(len(cur)): Rec(cur[i])
        elt = copy.deepcopy(elt)
        Rec(elt)
        return elt
    def StageTwo_TransformSubtree(self, elt): 
        eltTag = elt.tag; oldParent = elt.getparent()
        # See if 'elt' and its subtree should be moved somewhere higher up.
        (newParent, newSib) = self.FindSuitableParent(elt)
        #print("elt = %s, newParent = %s" % (etree.tostring(elt, pretty_print = False).decode("utf8"), newParent))
        if newParent is None: 
            #print("elt = %s, entry = %s" % (elt, self.entry))
            assert elt is self.transformedEntry
        elif not (newParent is elt.getparent()):
            # If all the nodes between 'elt' and 'newParent' are <seg>s, we can simply split them
            # and promote 'elt' to be a child of 'newParent'.
            allSegs = True
            anc = elt.getparent()
            while anc is not newParent:
                if anc.tag != ELT_seg: allSegs = False; break
                anc = anc.getparent()
            if allSegs:
                self.SplitToAncestor(elt, newParent)
                #print("After SplitToAncestor:\n%s" % etree.tostring(newParent, pretty_print = True).decode("utf8"))
            else:
                # Prepare a segified copy of 'elt' and its subtree.  Note that
                # most of the segification has already been done in phase 1;
                # we just have to rename all remaining non-<seg> tags into <seg>s.
                segifiedSubtree = self.MakeSegifiedCopy(elt)
                segifiedSubtree.tail = elt.tail
                # Replace 'elt' in its current place the segified copy of its subtree.
                idx = oldParent.index(elt); assert 0 <= idx < len(oldParent)
                oldParent[idx] = segifiedSubtree
                # Insert 'elt' (and its subtree) as a child of 'newParent'.
                idx = newParent.index(newSib); assert 0 <= idx < len(newParent)
                newParent.insert(idx + 1, elt)
                elt.tail = newSib.tail; newSib.tail = None
        # Otherwise we can transform each of elt's subtrees recursively.
        # Note that during these recursive calls, len(elt) may change if some 
        # subtrees are promoted from deeper below and become elt's children;
        # so we must not store len(elt) in a variable.
        #i = 0
        #while i < len(elt):
        #    self.StageTwo_TransformSubtree(elt[i])
        #    i += 1
    def StageTwo(self):
        cur = self.transformedEntry; prev = None
        # We have to be a bit careful when moving around the tree because
        # it will change while we do this -- a subtree can get promoted and
        # some of its ancestors split; and a copy of a subtree can be inserted
        # as a sibling of one of its ancestors.
        while cur is not None:
            if prev is None and type(cur) is TMyElement:
                # If we entered 'cur' from its parent, transform it now.
                self.StageTwo_TransformSubtree(cur)
            # If we entered from the parent, we'll move into the first child,
            # otherwise into the child following 'prev'.
            i = -1 if prev is None else cur.index(prev)
            if len(cur) > i + 1: prev = None; cur = cur[i + 1] # Move into the next child.
            else: prev = cur; cur = cur.getparent() # Move back into the parent.
    def StageOne_TransformSubtree(self, elt):
        if type(elt) is not TMyElement: return (copy.deepcopy(elt), None)
        class TOrder:
            TYPE_SIB = 1; TYPE_MILESTONES = 2; TYPE_CONSUME = 3
            # Note that the newElt of this order might not be what is called 'newElt' 
            # within the caller's context; it could be one of the newSibs, or a decendant 
            # created using milestones.  The newElt of this order is where typeAttr should
            # be applied, as well as trOrder.trLanguage.
            __slots__ = ["newTag", "trOrder", "typeAttr", "type", "newElt"]
            def __init__(self, newTag, trOrder, typeAttr = ""):
                self.newTag = newTag; self.trOrder = trOrder; self.typeAttr = typeAttr
                assert trOrder
                if trOrder.attr not in [ATTR_INNER_TEXT, ATTR_INNER_TEXT_REC, ATTR_CONSTANT]: 
                    # The data here is extracted from an attribute, not from the inner text.
                    # Thus we'll have to turn the original node into a <seg> and make a new
                    # sibling with the extracted value.
                    self.type = TOrder.TYPE_SIB
                elif trOrder.attrVal != trOrder.finalStr: 
                    # The transformation order collected the inner text (possibly recursively)
                    # and applied a regular expression to it, extracting only a part of the text.
                    # - Alternatively, perhaps the whole inner text was used, but it was then
                    # transformed with the xlat table.
                    # - Either way, we'll transform the current element into a <seg> and create a new
                    # descendant with a suitable tag somewhere below it.
                    self.type = TOrder.TYPE_MILESTONES
                else: 
                    # The transformation order used the entire inner text, so we'll try to
                    # simply consume the existing element.
                    self.type = TOrder.TYPE_CONSUME
        # Prepare a list of orders that apply to 'elt'.        
        eltId = id(elt); orders = []        
        if eltId in self.mDef: orders.append(TOrder(ELT_def, self.mDef[eltId]))
        if eltId in self.mPos: orders.append(TOrder(ELT_gram, self.mPos[eltId], typeAttr = "pos"))
        if eltId in self.mHw: orders.append(TOrder(ELT_orth, self.mHw[eltId], typeAttr = "lemma"))
        if eltId in self.mLemma: orders.append(TOrder(ELT_orth, self.mLemma[eltId], typeAttr = "simple"))
        if eltId in self.mHwTr: orders.append(TOrder(ELT_cit, self.mHwTr[eltId], typeAttr = "translationEquivalent"))
        if eltId in self.mEx: orders.append(TOrder(ELT_cit, self.mEx[eltId], typeAttr = "example"))
        if eltId in self.mExTr: orders.append(TOrder(ELT_cit, self.mExTr[eltId], typeAttr = "translation"))
        # Create siblings where needed.  
        consumers = []; newSibs = []
        for o in orders:
            if o.type == TOrder.TYPE_CONSUME: consumers.append(o)
            elif o.type == TOrder.TYPE_SIB:
                newSib = self.mapper.Element(o.newTag)
                newSib.text = o.trOrder.finalStr; newSibs.append(newSib)
                o.newElt = newSib
            elif o.type == TOrder.TYPE_MILESTONES: pass
        # There can be at most one consumer; others will be converted into milestone orders
        # and might result in the creation of descendants or siblings.
        if len(consumers) > 1:
            for o in consumers[1:]: o.type = TOrder.TYPE_MILESTONES
        consumer = consumers[0] if consumers else None
        # Create a new element.
        if consumer: newTag = consumer.newTag
        elif elt.tag == ELT_ENTRY_PLACEHOLDER: newTag = elt.tag
        else: newTag = ELT_seg
        newElt = self.mapper.Element(newTag)
        if consumer: consumer.newElt = newElt
        del newTag
        # Process the children.    
        newElt.text = elt.text
        for i in range(len(elt)):
            (newChild, newChildSibs) = self.StageOne_TransformSubtree(elt[i])
            assert newChild is not None
            newElt.append(newChild)
            for newChildSib in newChildSibs: newElt.append(newChildSib)
        # Do the milestone processing where necessary.
        for o in orders:
            if o.type != TOrder.TYPE_MILESTONES: continue
            if Verbose: logging.info("Before InsertMilestones:\n%s" % etree.tostring(newElt, pretty_print = True).decode("utf8"))
            o.trOrder.InsertMilestones(self.mapper, newElt)
            if Verbose: logging.info("After InsertMilestones:\n%s" % etree.tostring(newElt, pretty_print = True).decode("utf8"))
            if o.trOrder.msFrom is None:
                # The milestones couldn't be inserted because the inner text is already
                # different than it was in the original tree - most likely because of
                # new nodes being inserted to take into account transformation order
                # that involve regex matching and extracting a group.  Thus we'll have
                # to create a new sibling instead.
                newSib = self.mapper.Element(o.newTag)
                newSib.text = o.trOrder.finalStr
                newSibs.append(newSib)
                o.newElt = newSib
            else:
                newDescendant = self.InsertNewTagWithMilestones(newElt, o.newTag, o.trOrder)
                if Verbose: logging.info("After InsertNewTagWithMilestones:\n%s" % etree.tostring(newElt, pretty_print = True).decode("utf8"))
                o.newElt = newDescendant
                # ToDo: do anything with newDescendant?
            o.trOrder.RemoveMilestones()
            if Verbose: logging.info("After RemoveMilestones:\n%s" % etree.tostring(newElt, pretty_print = True).decode("utf8"))
        # If a <sense> or <entry> selector applies to 'elt', we'll either
        # rename newElt appropriately (if it's a <seg> now and there are no new siblings),
        # or we'll wrap it and the new siblings in a new <sense> or <entry>.
        def Wrap(mapper, newTag):
            nonlocal newElt, newSibs
            if newElt.tag == ELT_seg and not newSibs: newElt.tag = newTag; return
            newerElt = mapper.Element(newTag)
            if newElt.tag == ELT_seg and len(newElt) == 0 and not newElt.text:
                newerElt.text = newElt.tail
            else: newerElt.append(newElt)
            for sib in newSibs: newerElt.append(sib)
            newElt = newerElt; newSibs.clear()
        #print("eltId = %d, senseIds = %s" % (eltId, self.senseIds))    
        if eltId in self.senseIds: Wrap(self.mapper, ELT_sense)
        if elt is self.entry: Wrap(self.mapper, ELT_entry)
        # Set type and language attributes of the new elements of the transformation orders.
        newElt.set(ATTR_LEGACY_ELT, elt.tag)
        for o in orders:
            if o.typeAttr: o.newElt.set(ATTR_TEMP_type, o.typeAttr) 
            if o.trOrder.trLanguage is not None and o.trOrder.trLanguage.finalStr:
                o.newElt.set(ATTR_XML_LANG, o.trOrder.trLanguage.finalStr)
        # Transfer attributes from 'elt' into 'newElt' (the outermost new element).
        for (attrName, attrValue) in elt.items():
            if attrName == ATTR_ID: newElt.set(ATTR_LEGACY_ID, attrValue)
            elif attrName.startswith("{"): newElt.set(attrName, attrValue)
            else: newElt.set("{" + NS_ATTR + "}" + attrName, attrValue)
        newElt.originalElement = elt
        newElt.entryTime = getattr(elt, "entryTime", None)
        # The last sibling gets the original elt's tail; if there are no siblings, newElt gets it.
        if newSibs: newSibs[-1].tail = elt.tail
        else: newElt.tail = elt.tail
        return (newElt, newSibs)
    def StageOne_TransformSubtree_Old(self, elt):
        if type(elt) is not TMyElement: return (copy.deepcopy(elt), None)
        eltId = id(elt); trOrder = None; typeAttr = None
        if elt is self.entry: newTag = ELT_entry
        elif eltId in self.senseIds: newTag = ELT_sense
        elif eltId in self.mDef: newTag = ELT_def; trOrder = self.mDef[eltId]
        elif eltId in self.mPos: newTag = ELT_gram; trOrder = self.mPos[eltId]; typeAttr = "pos"
        elif eltId in self.mHw: newTag = ELT_orth; trOrder = self.mHw[eltId]; typeAttr = "lemma"
        elif eltId in self.mLemma: newTag = ELT_orth; trOrder = self.mLemma[eltId]; typeAttr = "simple"
        elif eltId in self.mHwTr: newTag = ELT_cit; trOrder = self.mHwTr[eltId]; typeAttr = "translationEquivalent"
        elif eltId in self.mEx: newTag = ELT_cit; trOrder = self.mEx[eltId]; typeAttr = "example"
        elif eltId in self.mExTr: newTag = ELT_cit; trOrder = self.mExTr[eltId]; typeAttr = "translation"
        elif elt.tag == ELT_ENTRY_PLACEHOLDER: newTag = elt.tag
        else: newTag = ELT_seg
        needsMilestones = False; newSib = None
        if trOrder != None and trOrder.finalStr != trOrder.matchedStr:
            print("# %s -> %s" % (trOrder.matchedStr, trOrder.finalStr))
        if trOrder != None and trOrder.attr != ATTR_INNER_TEXT and trOrder.attr != ATTR_INNER_TEXT_REC and trOrder.attr != ATTR_CONSTANT:
            # The data here is extracted from an attribute, not from the inner text.
            # Thus we'll have to turn the original node into a <seg> and make a new
            # sibling with the extracted value.
            newElt = self.mapper.Element(ELT_seg)
            newSib = self.mapper.Element(newTag)
            newElt.tail = None; newSib.tail = elt.tail
            newSib.text = trOrder.finalStr
        elif trOrder is not None and (True or trOrder.rexMatch is not None) and trOrder.attrVal != trOrder.finalStr:  
            # The transformation order collected the inner text (possibly recursively)
            # and applied a regular expression to it, extracting only a part of the text.
            # - Alternatively, perhaps the whole inner text was used, but it was then
            # transformed with the xlat table.
            # - Either way, we'll transform the current element into a <seg> and create a new
            # descendant with a suitable tag somewhere below it.
            newElt = self.mapper.Element(ELT_seg)
            newElt.tail = elt.tail
            needsMilestones = True
        else:
            newElt = self.mapper.Element(newTag)
            newElt.tail = elt.tail
        # Process the attributes.
        newElt.set(ATTR_LEGACY_ELT, elt.tag)
        if typeAttr: newElt.set(ATTR_TEMP_type, typeAttr)
        if trOrder is not None and trOrder.trLanguage is not None and trOrder.trLanguage.finalStr:
            newElt.set(ATTR_XML_LANG, trOrder.trLanguage.finalStr)
        for (attrName, attrValue) in elt.items():
            if attrName == ATTR_ID: newElt.set(ATTR_LEGACY_ID, attrValue)
            elif attrName.startswith("{"): newElt.set(attrName, attrValue)
            else: newElt.set("{" + NS_ATTR + "}" + attrName, attrValue)
        newElt.originalElement = elt
        newElt.entryTime = getattr(elt, "entryTime", None)
        # Process the children.    
        newElt.text = elt.text
        for i in range(len(elt)):
            (newChild, newChildSib) = self.StageOne_TransformSubtree(elt[i])
            assert newChild is not None
            newElt.append(newChild)
            if newChildSib is not None: newElt.append(newChildSib)
        # Do the milestone processing if necessary.
        if needsMilestones:
            if Verbose: logging.info("Before InsertMilestones:\n%s" % etree.tostring(newElt, pretty_print = True).decode("utf8"))
            trOrder.InsertMilestones(self.mapper, newElt)
            if Verbose: logging.info("After InsertMilestones:\n%s" % etree.tostring(newElt, pretty_print = True).decode("utf8"))
            if trOrder.msFrom is None:
                # The milestones couldn't be inserted because the inner text is already
                # different than it was in the original tree - most likely because of
                # new nodes being inserted to take into account transformation order
                # that involve regex matching and extracting a group.  Thus we'll have
                # to create a new sibling instead.
                newSib = self.mapper.Element(newTag)
                newElt.tag = ELT_seg 
                newElt.tail = None; newSib.tail = elt.tail
                newSib.text = trOrder.finalStr
            else:
                newDescendant = self.InsertNewTagWithMilestones(newElt, newTag, trOrder)
                if Verbose: logging.info("After InsertNewTagWithMilestones:\n%s" % etree.tostring(newElt, pretty_print = True).decode("utf8"))
                # ToDo: do anything with newDescendant?
            trOrder.RemoveMilestones()
            if Verbose: logging.info("After RemoveMilestones:\n%s" % etree.tostring(newElt, pretty_print = True).decode("utf8"))
        return (newElt, newSib)
    def SplitToAncestor(self, ms, anc):
        # We assume that 'ms' is a descendant of 'anc', and that all the
        # nodes on the path between them are <seg>s.  We will split them and
        # promote the 'ms' to become a child of 'anc'.
        while ms.getparent() is not anc:
            parent = ms.getparent(); idx = parent.index(ms); nChildren = len(parent)
            grandparent = parent.getparent(); pidx = grandparent.index(parent)
            assert parent.tag == ELT_seg
            anyLeft = (IsNonSp(parent.text) or idx > 0)
            anyRight = (IsNonSp(ms.tail) or idx + 1 < nChildren)
            if not anyLeft:
                # In 'parent', there's nothing left of 'ms', so we can just
                # remove 'ms' and reinsert it as a left sibling of 'parent'.
                parent.text = ms.tail; ms.tail = None
                parent.remove(ms); grandparent.insert(pidx, ms)
                continue
            elif not anyRight:
                # In 'parent', there's nothing right of 'ms', so we can just
                # remove 'ms' and reinsert it as a right sibling of 'parent'.
                ms.tail = parent.tail; parent.tail = None
                parent.remove(ms); grandparent.insert(pidx + 1, ms)
                continue
            # Otherwise we will actually have to split the parent.
            # Create a new sibling and copy the attributes into it.
            sib = self.mapper.Element(ELT_seg)
            for attrName, attrValue in parent.items(): 
                #or attrName == "xml:id"
                if attrName == ATTR_ID: pass # this shouldn't be happening anyway
                elif attrName.startswith("{"): sib.set(attrName, attrValue)
                else: sib.set("{" + NS_ATTR + "}" + attrName, attrValue)
            # Fill 'sib' with everything to the right of 'ms'.    
            sib.text = ms.tail; ms.tail = None
            i = idx + 1
            #print("SplitToAncestor: parent = %s, sib = %s, idx = %d, ms = %s" % (parent, sib, idx, ms))
            #print("len[parent] = %s, parent[%d] = %s" % (len(parent), idx, parent[idx]))
            #print("len[parent] = %s" % len(parent))
            while i < nChildren:
                c = parent[idx + 1]; parent.remove(c); sib.append(c); i += 1
            #print("len[parent] = %s, parent[%d] = %s" % (len(parent), idx, parent[idx]))
            # Remove 'ms' from 'parent', insert it and 'sib' as the
            # right siblings of 'parent'.
            parent.remove(ms)
            sib.tail = parent.tail; parent.tail = None
            grandparent.insert(pidx + 1, sib)
            grandparent.insert(pidx + 1, ms)
    def InsertNewTagWithMilestones(self, root, newTag, trOrder):
        # This assumes that the milestones have already been inserted.
        assert trOrder.msFrom 
        # Run a depth-first search and store the depth and start/end time in every node.
        curTime = 0
        def Rec(elt, depth):
            nonlocal curTime
            elt.depth = depth; elt.startTime = curTime; curTime += 1
            for i in range(len(elt)): Rec(elt[i], depth + 1)
            elt.endTime = curTime; curTime += 1
        Rec(root, 0)
        #
        if not trOrder.msTo:
            # There are only end milestones, no start milestones, which means
            # that the regex matched an empty string.  We'll insert a new element 
            # with empty content at the point of one of the milestones.
            msBest = None
            for ms in trOrder.msFrom:
                if msBest is None or ms.depth < msBest.depth: msBest = ms
            assert msBest is not None
            newElt = self.mapper.Element(newTag)
            newElt.tail = msBest.tail; msBest.tail = None
            parent = msBest.getparent(); idx = parent.index(msBest)
            parent.insert(idx + 1, newElt)
            return newElt
        #
        def Anc(a, b):
            anc = a
            while not (anc.startTime <= b.startTime and b.endTime <= anc.endTime): anc = anc.getparent()
            return anc
        # Choose the most suitable pair of start and end milestone.
        bestMsPair = None; bestScore = None
        for ms in trOrder.msFrom:
            for me in trOrder.msTo:
                # The end milestone has to be after the start milestone.
                if not (ms.endTime < me.startTime): continue
                anc = Anc(ms, me) # the deepest common ancestor of ms and me
                # Count how many nodes would have to be split if we use this
                # pair of milestones, and how many of them are non-<seg>s.
                nSplits = 0; nNonSegs = 0
                def Count(elt):
                    nonlocal nSplits, nNonSegs
                    if elt is anc: return
                    elt = elt.getparent()
                    while elt is not anc:
                        nSplits += 1
                        if elt.tag != ELT_seg: nNonSegs += 1
                        elt = elt.getparent()
                Count(ms); Count(me)
                # We don't actually want to split non-segs, so we'll try to
                # minimize nNonSegs; the next criterion is to minimize splitting of
                # segs themselves, and finally minimizing anc.depth so the resulting
                # new node is higher up in the tree if possible.
                score = (nNonSegs, nSplits, anc.depth)
                if bestMsPair is None or score < bestScore:
                    bestMsPair = (ms, me); bestScore = score
        assert bestMsPair; assert bestScore
        # If it's impossible to avoid splitting a non-<seg> node, we won't insert a new node at all.
        # The caller will have to create a new node somewhere else.
        if bestScore[0] > 0: return None
        (ms, me) = bestMsPair; anc = Anc(ms, me)
        # The ancestors between 'ms' and 'anc' are <seg>s, and we have to split all of them;
        # likewise those between 'me' and 'anc'.
        self.SplitToAncestor(ms, anc)
        self.SplitToAncestor(me, anc)
        assert ms.getparent() is anc; assert me.getparent() is anc
        newElt = self.mapper.Element(newTag)
        iMs = anc.index(ms); iMe = anc.index(me)
        newElt.tail = me.tail; me.tail = None
        for i in range(iMs, iMe + 1):
            child = anc[iMs]; anc.remove(child); newElt.append(child)
        anc.insert(iMs, newElt)
        return newElt
    def StageOne(self):
        # In this stage, we'll make a copy of the tree in which 
        # the tags of the nodes (and the attributes) are suitably transformed,
        # regardless of whether the resulting parent-child relationships
        # are compatible with the model or not.
        (newEntry, newSibs) = self.StageOne_TransformSubtree(self.entry)
        assert len(newSibs) == 0
        return newEntry
#    seg                                       -> CDATA, seg
#    form/orth, def, gramGrp/gram, cit/quote   -> CDATA, seg, cit
#    sense                                     -> CDATA, seg, cit, sense, form, gramGrp, def  
#    dictScrap                                 -> CDATA  seg  cit  sense  form  gramGrp  def  
#    entry                                     ->             cit  sense  form, gramGrp      dictScrap entry 
    def StageThree_ProcessSubtree(self, elt):
        nChildren = len(elt)
        for i in range(nChildren): self.StageThree_ProcessSubtree(elt[i])
        parent = elt.getparent()
        if elt.tag == ELT_orth: # orth -> form/orth
            newNode = self.mapper.Element(ELT_form)
            i = parent.index(elt); assert 0 <= i < len(parent)
            parent[i] = newNode; newNode.append(elt)
            ty = elt.get(ATTR_TEMP_type, None)
            if ty is not None: 
                newNode.set(ATTR_type_UNPREFIXED, ty) # the type attribute moves to <form>
                elt.attrib.pop(ATTR_TEMP_type, None)
        elif elt.tag == ELT_cit: # cit -> cit/quote
            newNode = self.mapper.Element(ELT_cit)
            i = parent.index(elt); assert 0 <= i < len(parent)
            parent[i] = newNode; newNode.append(elt)
            elt.tag = ELT_quote
            ty = elt.get(ATTR_TEMP_type, None)
            #print("tag = %s, ty = %s" % (elt.tag, ty))
            if ty is not None: 
                #print("About to set type [%s].  %s" % (elt.tag, elt.nsmap))
                # If we use ATTR_type here, etree adds an unnecessary additional namespace prefix
                # instead of recognizing that, since this attribute is from the same namespace as
                # the element, it could remain unprefixed when serializing the document..
                # To avoid this, we'll just set it without a prefix.
                # [Note: https://www.w3.org/TR/xml-names/#scoping-defaulting says that "Default 
                # namespace declarations do not apply directly to attribute names; the interpretation 
                # of unprefixed attributes is determined by the element on which they appear.".]
                newNode.set(ATTR_type_UNPREFIXED, ty) # the type attribute goes into <cit>, not <quote>  
                #print("After setting type.  %s" % elt.nsmap)
                elt.attrib.pop(ATTR_TEMP_type, None)
        elif elt.tag == ELT_gram: # gram -> gramGrp/gram
            newNode = self.mapper.Element(ELT_gramGrp)
            i = parent.index(elt); assert 0 <= i < len(parent)
            parent[i] = newNode; newNode.append(elt)
            ty = elt.get(ATTR_TEMP_type, None)
            if ty is not None: 
                elt.set(ATTR_type_UNPREFIXED, ty) # the type attribute stays in <gram>
                elt.attrib.pop(ATTR_TEMP_type, None)
        elif elt.tag == ELT_entry:
            # An entry may not contain <seg>s, so they should be changed into <dictScraps>.
            # It may also not contain character data and <def>s, so we'll wrap those things into <dictScraps>.
            if IsNonSp(elt.text):
                child = self.mapper.Element(ELT_dictScrap); child.text = elt.text
                elt.insert(0, child)
            elt.text = None
            i = 0
            while i < len(elt):
                child = elt[i]
                if IsNonSp(child.tail): 
                    sib = self.mapper.Element(ELT_dictScrap); sib.text = child.tail
                    elt.insert(i + 1, sib)
                child.tail = None    
                if child.tag == ELT_seg: 
                    child.tag = ELT_dictScrap
                elif child.tag == ELT_def:
                    newChild = self.mapper.Element(ELT_dictScrap)
                    elt[i] = newChild; newChild.append(child)
                i += 1
    def StageThree(self):
        self.StageThree_ProcessSubtree(self.transformedEntry)
    def TransformEntry(self): 
        self.senseIds = set(id(x) for x in ([] if not self.m.selSense else self.m.selSense.findall(self.entry)))
        #mSense = self.MakeTrOrderHashFromSelector(self.m.selSense)
        self.mDef = self.MakeTrOrderHash(self.m.xfDef, MATCH_def)
        self.mPos = self.MakeTrOrderHash(self.m.xfPos, MATCH_pos)
        self.mHw = self.MakeTrOrderHash(self.m.xfHw, MATCH_hw)
        self.mLemma = self.MakeTrOrderHash(self.m.xfLemma, MATCH_lemma)
        self.mHwTrLang = self.MakeTrOrderHash(self.m.xfHwTrLang, MATCH_hw_tr_lang)
        self.mHwTr = self.MakeTrOrderHash(self.m.xfHwTr, MATCH_hw_tr)
        self.mEx = self.MakeTrOrderHash(self.m.xfEx, MATCH_ex)
        self.mExTrLang = self.MakeTrOrderHash(self.m.xfExTrLang, MATCH_ex_tr_lang)
        self.mExTr = self.MakeTrOrderHash(self.m.xfExTr, MATCH_ex_tr)
        self.FindLanguageAll(self.mHwTr, self.mHwTrLang)
        self.FindLanguageAll(self.mExTr, self.mExTrLang)
        if Verbose: print("TEntryMapper: %d sense elements, %d headwords, %d lemmas, %s definitions, %d part-of-speech, %d translations (%d lang), %d examples, %d translated examples (%d lang)." % (
            len(self.senseIds), len(self.mHw), len(self.mLemma), len(self.mDef), len(self.mPos), len(self.mHwTr), len(self.mHwTrLang),
            len(self.mEx), len(self.mExTr), len(self.mExTrLang)))
        #traceback.print_stack()    
        # Insert milestone elements where needed.  Note that we don't need
        # them for the language elements since those won't be transformed into
        # element, but into attributes.
        #for h in (self.mDef, self.mPos, self.mHwTr, self.mEx, self.mExTr):
        #    for order in h.values(): order.InsertMilestones(self.mapper)
        #print("After insertion of milestones:\n%s" % etree.tostring(self.entry, pretty_print = True).decode("utf8"))
        # Create a copy of the entry's subtree with tags suitably renamed..
        self.transformedEntry = self.StageOne()
        assert self.transformedEntry is not None
        assert self.transformedEntry.tag == ELT_entry
        if Verbose: print("After stage one:\n%s" % etree.tostring(self.transformedEntry, pretty_print = True).decode("utf8"))
        # Move things around when needed to set up proper parent/child relationships.
        self.StageTwo()
        assert self.transformedEntry.tag == ELT_entry
        if Verbose: print("After stage two:\n%s" % etree.tostring(self.transformedEntry, pretty_print = True).decode("utf8"))
        # Stage 3: expand orth into form/orth, gram into gramGrp/gram, and cit into cit/quote;
        # and if the root <entry> has any children of the wrong type, wrap them into <dictScrap>s.
        self.StageThree()
        if Verbose: print("After stage three:\n%s" % etree.tostring(self.transformedEntry, pretty_print = True).decode("utf8"))
        #transformedEntry = self.mapper.Element(ELT_entry)
        #transformedEntry.entryTime = self.entry.entryTime
        # The language was set by the caller in self.entry.xmlLangAttribute, if available.
        lang = getattr(self.entry, "xmlLangAttribute", None)
        if lang is not None: self.transformedEntry.set(ATTR_XML_LANG, lang)
        self.transformedEntry.set(ATTR_type_UNPREFIXED, "null")
        return self.transformedEntry

def IsNonSp(s): return s and not s.isspace()

def SetMatchInfo(e, match, attr = None, from_ = None, to_ = None):
    if e is None: return
    ae = getattr(e, "augNode", None)
    if ae is None: return
    #print("SetMatchInfo, e = %s, match = %s, attr = %s" % (e, match, attr))
    attrib = ae.attrib
    def _(a, v):
        if v is not None: attrib[a] = v
        elif a in attrib: del attrib[a]
    _(ATTR_MATCH, match)
    _(ATTR_MATCH_ATTR, attr)
    _(ATTR_MATCH_FROM, from_)
    _(ATTR_MATCH_TO, to_)

augmentedNodes = set()

class TTreeMapper:
    __slots__ = [
        "tree", # the etree we are processing
        "m", # the TMapping we are using to process the tree
        "parser", # the XMLParser object used to construct the tree
        "eltHash", "entryHash", # key: id; value: the corresponding element
        "topEntryList", # list of elements that are entries and are not contained in another entry; in-order traversal order
        "entryPlaceholders", # list of placeholders for transformed entries
        "keepAliveHash", # all elements anyhwere, to make sure lxml doesn't recycle the instances
        "relaxNg", # the schema loaded from TEILex0-ODD.rng
        "outBody", # the resulting <body> element, with <entry>es as its chldren
        "augTree", # a copy of the input tree, to be augmented with attributes about the transformation
        ]
    def __init__(self, tree, m, parser, relaxNg, makeAugTree): # m = mapping
        self.tree = tree
        self.m = m
        self.parser = parser
        self.keepAliveHash = {}
        self.relaxNg = relaxNg
        self.augTree = None
        if makeAugTree: 
            augRoot = self.MakeAugTree(self.tree.getroot())
            self.augTree = etree.ElementTree(augRoot)
    def Clear(self):
        self.tree = None; self.m = None; self.parser = None
        self.eltHash.clear(); self.entryHash.clear()
        self.topEntryList.clear(); self.keepAliveHash.clear()
        self.relaxNg = None; self.outBody = None; self.augTree = None
    def MakeAugTree(self, e):    
        if Verbose2 and len(augmentedNodes) % 1000 == 0: sys.stdout.write("MakeAugTree keepAliveHash %d, augmentedNodes %d  \r" % (len(self.keepAliveHash), len(augmentedNodes))); sys.stdout.flush()
        nsmap = e.nsmap
        if NS_META not in nsmap.values():
            n = 0
            while True:
                key = "m" + (str(n) if n > 0 else "")
                if key in nsmap: n += 1
                else: nsmap[key] = NS_META; break
        ae = self.parser.makeelement(e.tag, e.attrib, nsmap)
        self.keepAliveHash[id(e)] = e
        self.keepAliveHash[id(ae)] = ae
        ae.text = e.text; ae.tail = e.tail
        e.augNode = ae
        augmentedNodes.add(id(e))
        #if e.tag == "Artikel": print("Setting %s.augNode to %s" % (e, ae))
        for child in e: ae.append(self.MakeAugTree(child))
        return ae
    def FindEntries(self, root):
        self.eltHash = {}; self.entryHash = {}
        for x in self.tree.iter(): 
            self.eltHash[id(x)] = x
        for x in self.m.selEntry.findall(root):
            if x.tag == ELT_TEMP_ROOT: continue
            #if id(x) not in augmentedNodes: print("Warning: %s not found among %d augmented nodes." % (x, len(augmentedNodes)))
            self.entryHash[id(x)] = x
        #print("%d entries found." % len(self.entryHash))    
    def Element(self, *args, **kwargs):
        e = self.parser.makeelement(*args, **kwargs, nsmap = NS_MAP)
        self.keepAliveHash[id(e)] = e
        return e
    def E(self, tag, attrib_ = {}, children = [], text = None, tail = None):
        e = self.parser.makeelement(tag, attrib = attrib_, nsmap = NS_MAP)
        for child in children: e.append(child)
        e.text = text; e.tail = tail
        self.keepAliveHash[id(e)] = e
        return e
    def InsertTempRoot(self, e):
        if e.tag == ELT_TEMP_ROOT: return e
        r = self.E(ELT_TEMP_ROOT); r.append(e); return r
    def RemoveTempRoot(self, e):
        if e is None or e.tag != ELT_TEMP_ROOT: return e
        assert len(e) == 1; assert not e.text; assert not e.tail
        r = e[0]; e.remove(r)
        assert r.getparent() is None
        return r
    def MarkEntries(self):
        # This method goes through the tree recursively and adds
        # the following attributes to each element:
        # - outermostContainingEntry: id of the outermost entry containing this element (excluding this element itself), or None
        # - firstSubEntry, lastSubEntry: id of the first/last entry in the subtree rooted by this element (excluding this element itself)
        # - isEntry: boolean indicating if this element is an entry or not.
        # - entryTime, exitTime: time when we entered/exited this element in the in-order traversal
        # It also builds self.topEltList.
        counter = 0; tmStart = time.clock(); tmPrev = tmStart; counterPrev = counter
        self.topEntryList = []
        def Rec(elt, outermostContainingEntry):
            nonlocal counter, tmPrev, counterPrev
            if type(elt) is not TMyElement: return
            elt.entryTime = counter; counter += 1
            elt.isEntry = id(elt) in self.entryHash
            elt.outermostContainingEntry = outermostContainingEntry
            if elt.isEntry and not outermostContainingEntry:
                outermostContainingEntry = id(elt)
                self.topEntryList.append(elt)
            nChildren = len(elt)
            firstSubEntry = None; lastSubEntry = None
            # Note: it turns out that accessing a child as elt[iChild] takes O(iChild) time rather than O(1)
            # time.  If we enumerate the children into a separate list and then access that, the overall time
            # spent in MarkEntries is very substantially reduced.
            children = [child for child in elt]; nChildren = len(children)
            #if nChildren >= 1000: print("Note: elt has %d children!" % nChildren)
            for iChild in range(nChildren):
                child = children[iChild] # child = elt[iChild]
                if type(child) is not TMyElement: continue
                Rec(child, outermostContainingEntry)
                s = id(child) if child.isEntry else child.firstSubEntry
                if s and not firstSubEntry: firstSubEntry = s
                s = id(child) if child.isEntry else child.lastSubEntry
                if s: lastSubEntry = s
            elt.firstSubEntry = firstSubEntry
            elt.lastSubEntry = lastSubEntry
            elt.exitTime = counter; counter += 1
            if Verbose2 and counter % 10000 == 0: 
                tmNow = time.clock()
                sys.stdout.write("MarkEntries %d (%.2f sec, %.2f counts/sec, recently %.2f)    \r" % (counter, tmNow - tmStart,
                    counter / max(tmNow - tmStart, 0.1), (counter - counterPrev) / max(0.01, tmNow - tmPrev))); sys.stdout.flush()
                counterPrev = counter; tmPrev = tmNow
        Rec(self.tree.getroot(), None)    
        #for entry in self.topEntryList: print("Entry [id = %d] time %d..%d" % (id(entry), entry.entryTime, entry.exitTime))
    def SegifyElt(self, elt):
        # Returns a <seg> corresponding to the given 'elt' and copies the attributes into it.
        if type(elt) is not TMyElement: return copy.deepcopy(elt)
        seg = self.Element(ELT_seg, {ATTR_LEGACY_ELT: elt.tag, ATTR_LEGACY_SRC: str(elt.entryTime)})
        for attrName, attrValue in elt.items(): 
            #or attrName == "xml:id"
            if attrName == ATTR_ID: seg.set(ATTR_LEGACY_ID, attrValue)
            elif attrName.startswith("{"): seg.set(attrName, attrValue)
            else: seg.set("{" + NS_ATTR + "}" + attrName, attrValue)
        seg.text = elt.text; seg.tail = elt.tail    
        return seg
    def SegifySubtree(self, elt):
        # Returns a <seg> corresponding to the entire subtree rooted by 'elt'.
        seg = self.SegifyElt(elt)
        nChildren = len(elt)
        for iChild in range(nChildren):
            seg.append(self.SegifySubtree(elt[iChild]))
        return seg    
    def ScrapifyLeft(self, entry):
        # Returns a <dictScrap> with the segified versions of everything to the left
        # of the branch from 'entry' to the root.  If there was nothing there (because 'entry'
        # is on the leftmost branch and the 'text' attribute was empty for all the ancestors of 'entry'),
        # it returns None instead.
        scrap = self.Element(ELT_dictScrap)
        anythingScrapped = False
        cur = entry; root = self.tree.getroot()
        segCur = None
        while not (cur is root):
            parent = cur.getparent()
            iCur = parent.index(cur)
            assert iCur >= 0
            #print("cur = %s, parent = %s, iCur = %d" % (cur, parent, iCur))
            segParent = self.SegifyElt(parent)
            segParent.tail = ""
            if IsNonSp(segParent.text): anythingScrapped = True
            if iCur > 0:
                for iSib in range(iCur):
                    segSib = self.SegifySubtree(parent[iSib])
                    segParent.append(segSib)
                    anythingScrapped = True
            cur = parent
            if segCur is not None: segParent.append(segCur)
            segCur = segParent
        if anythingScrapped: 
            scrap.append(segCur)
            # If the <dictScrap> contains just one <seg> and nothing else, we can simply 
            # promote this seg to a <dictScrap> instead.
            if not IsNonSp(scrap.text) and len(scrap) == 1 and scrap[0].tag == ELT_seg and not IsNonSp(scrap[0].tail):
                scrap = scrap[0]; scrap.tag = ELT_dictScrap
        return scrap if anythingScrapped else None    
    def ScrapifyRight(self, entry):
        # Like ScrapifyLeft, but right of the branch.  
        # The scrap also receives entry.tail.
        scrap = self.Element(ELT_dictScrap)
        anythingScrapped = False
        cur = entry; root = self.tree.getroot()
        segCur = None
        while not (cur is root):
            parent = cur.getparent()
            iCur = parent.index(cur); nChildren = len(parent)
            assert iCur >= 0
            #print("cur = %s, parent = %s, iCur = %d" % (cur, parent, iCur))
            segParent = self.SegifyElt(parent)
            segParent.text = entry.tail if cur is entry else ""
            if IsNonSp(segParent.text) or IsNonSp(segParent.tail): anythingScrapped = True
            if segCur is not None: segParent.append(segCur)
            if iCur < nChildren - 1:
                for iSib in range(iCur + 1, nChildren):
                    segSib = self.SegifySubtree(parent[iSib])
                    segParent.append(segSib)
                    anythingScrapped = True
            cur = parent
            segCur = segParent
        if anythingScrapped: 
            scrap.append(segCur)
            # If the <dictScrap> contains just one <seg> and nothing else, we can simply 
            # promote this seg to a <dictScrap> instead.
            if not IsNonSp(scrap.text) and len(scrap) == 1 and scrap[0].tag == ELT_seg and not IsNonSp(scrap[0].tail):
                scrap = scrap[0]; scrap.tag = ELT_dictScrap
        return scrap if anythingScrapped else None    
    def ScrapifyBetween(self, entryL, entryR):
        # The two entries must be on separate branches, i.e. neither being an ancestor of the other.
        # This method returns a pair of scraps that, taken together, contain everything between 
        # the two entries, including entryL's tail.
        assert not entryL.IsAncestorOf(entryR) and not entryR.IsAncestorOf(entryL)
        # Let C be the lowest common ancestor L and R.  So we have something like
        #  <C> ... <a2> ... <a1> ... <L/> L.tail [A1] </a1> a1.tail [A2] </a2> a2.tail [gamma] <b2> b2.text [B2] <b1> b1.text [B1] <R/> ... </b1> ... </b2> ... </C>
        # Here we assumed that there are exactly 2 nodes between C and L, and also exactly 2 between C and R.
        # In practice there may be 0 or more, and the two branches can vary in depth.
        # "..." stands for a text/tail followed by 0 or more siblings that are not of interest to us here.
        # "A_i" stands for 0 or more sibling subtrees (with tails) under a_i, and likewise "B_i" under b_i and "gamma" under C.
        # The scrap that we're trying to construct must cover the part between <L/> and <R/>, i.e. this:
        #    L.tail [A1] </a1> a1.tail [A2] </a2> a2.tail [gamma] <b2> b2.text [B2] <b1> b1.text [B1]
        # In principle we could put all this into one scrap and either append it at the 
        # end of entryL or insert it at the start of entryR.  However, to make the structures
        # look nicer, we'll try to put the left part of the path into the left entry and the right
        # part into the right entry.  Thus we'll start with:
        #    L.tail [A1] </a1> a1.tail [A2] </a2> a2.tail [gamma] <b2> b2.text [B2] <b1> b1.text [B1]
        #    \------------------------------------------/         \---------------------------------/
        #               lScrap                                                rScrap
        # We'll append [gamma] at the end of 'lScrap', except if it's empty and rScrap isn't, 
        # in which case we'll prepend it at the start of 'rScrap'.
        #  lScrap = <dictScrap> <a2> <a1> L.tail [A1] </a1> a1.tail [A2] </a2> a2.tail </dictScrap> 
        #  rScrap = <dictScrap> <b2> b2.text [B2] <b1> b1.text [B1] </b1> </b2> </dictScrap> 
        anythingScrappedL = False
        segCur = None; lca = None; cur = entryL; leftTailToDo = entryL.tail
        while True:
            parent = cur.getparent(); iCur = parent.index(cur); assert iCur >= 0
            #print("Going up the left branch.  parent = %s" % id(parent))
            if parent.IsAncestorOf(entryR): 
                lca = parent; lcaLeftBranch = iCur; break
            nChildren = len(parent)
            #print("cur = %s, parent = %s, iCur = %d" % (cur, parent, iCur))
            segParent = self.SegifyElt(parent)
            segParent.text = entryL.tail if cur is entryL else ""
            leftTailToDo = None # was consumed
            if IsNonSp(segParent.text) or IsNonSp(segParent.tail): anythingScrappedL = True
            if segCur is not None: segParent.append(segCur)
            if iCur < nChildren - 1:
                for iSib in range(iCur + 1, nChildren):
                    segSib = self.SegifySubtree(parent[iSib])
                    segParent.append(segSib)
                    anythingScrappedL = True
            cur = parent; segCur = segParent
        segL = segCur
        #
        anythingScrappedR = False; segCur = None; cur = entryR
        while True:
            parent = cur.getparent()
            #print("Going up the right branch.  parent = %s, lca = %s" % (id(parent), id(lca)))
            iCur = parent.index(cur); assert iCur >= 0
            if parent is lca: lcaRightBranch = iCur; break
            segParent = self.SegifyElt(parent)
            segParent.tail = ""
            if IsNonSp(segParent.text): anythingScrappedR = True
            if iCur > 0:
                for iSib in range(iCur):
                    segSib = self.SegifySubtree(parent[iSib])
                    segParent.append(segSib)
                    anythingScrapped = True
            cur = parent
            if segCur is not None: segParent.append(segCur)
            segCur = segParent
        segR = segCur
        # segL and segR now contain segified versions of everything below the LCA.
        # Let's add a segged version of the LCA itself.
        lcaL = self.SegifyElt(lca); lcaL.text = ""; lcaL.tail = ""
        lcaR = self.SegifyElt(lca); lcaR.text = ""; lcaR.tail = ""
        # Add segified versions of the subtrees (under 'lca') between the two branches.
        # This is also the time to add entryL's tail, if we haven't added it yet.
        # Normally we should have added it to the innermost level of the left scrap,
        # but is entryL is a direct child of 'lca', then the left scrap is empty and
        # we'll treat entryL's tail much as if it was another of lca's subtrees between
        # the two branches.  entryL's tail will move into lcaL's text or lcaR's text, same
        # as those subtrees.
        nChildren = len(lca)
        #print("lca has %d children, left = %d, right = %d" % (nChildren, lcaLeftBranch, lcaRightBranch))
        assert 0 <= lcaLeftBranch < lcaRightBranch < nChildren
        if segL is not None: lcaL.append(segL)
        if lcaRightBranch - lcaLeftBranch > 1 or leftTailToDo:
            if anythingScrappedR and not anythingScrappedL: dest = lcaR; anythingScrappedR = True
            else: dest = lcaL; anythingScrappedL = True
            if leftTailToDo: dest.text = leftTailToDo; leftTailToDo = None
            for iChild in range(lcaLeftBranch + 1, lcaRightBranch):
                dest.append(self.SegifySubtree(lca[iChild]))
        if segR is not None: lcaR.append(segR)
        # Now add segified versions of all the ancestors of 'lca'.
        cur = lca; root = self.tree.getroot()
        segL = lcaL; segR = lcaR
        while not (cur is root):
            cur = cur.getparent()
            t = segL; segL = self.SegifyElt(cur); segL.text = None; segL.tail = None; segL.append(t)
            t = segR; segR = self.SegifyElt(cur); segR.text = None; segR.tail = None; segR.append(t)
        return (segL if anythingScrappedL else None, segR if anythingScrappedR else None)
    def TransformDetachedEntry(self, entry):
        # Builds (and returns) a transformed version of 'entry', which is assumed to have
        # been detached from the tree.
        assert entry.getparent() is None
        SetMatchInfo(entry, MATCH_entry)
        entryMapper = TEntryMapper(entry, self.m, self.parser, self)
        return entryMapper.TransformEntry()
        #return transformedEntry
    def TransformEntry(self, entry):
        # Replace 'entry' in its current tree with a placeholder element,
        # whose 'transformedEntry' member will point to the transformed version of 'entry'.
        # This is intended to be used for non-nested entries, so the placeholder
        # is not added to 'self.placeholders'.
        parent = entry.getparent()
        if parent is not None: idx = parent.index(entry); assert idx >= 0
        placeholder = self.Element(ELT_ENTRY_PLACEHOLDER)
        #if addToPlaceholders: self.entryPlaceholders.append(placeholder)
        if parent is not None: parent[idx] = placeholder; assert entry.getparent() is None
        placeholder.transformedEntry = self.TransformDetachedEntry(entry)
        return placeholder
    def TransformNonTopEntries(self):
        # We'll process the non-top entries in increasing order of exitTime.
        # This ensures that subentries are processed before their parent entries.
        L = [(entry.exitTime, entry) for entry in self.entryHash.values() if not (entry.outermostContainingEntry is None)]
        assert len(L) == len(self.entryHash) - len(self.topEntryList)
        L.sort()
        self.entryPlaceholders = []
        for dummy, entry in L: 
            parent = entry.getparent(); assert not (parent is None)
            idx = parent.index(entry); assert idx >= 0
            placeholder = self.Element(ELT_ENTRY_PLACEHOLDER)
            self.entryPlaceholders.append(placeholder)
            parent[idx] = placeholder; assert entry.getparent() is None
            print("Transforming detached entry %d %s" % (id(entry), entry))
            placeholder.transformedEntry = self.TransformDetachedEntry(entry)
            #print("Transformed entry: %s %d" % (placeholder.transformedEntry, len(placeholder.transformedEntry)))
    def ReplacePlaceholders(self, root):  # for non-top entries
        #for placeholder in self.entryPlaceholders:
        def Rec(elt):
            for i in range(len(elt)): Rec(elt[i])
            if elt.tag == ELT_ENTRY_PLACEHOLDER:
                placeholder = elt.originalElement
                print("Placeholder = %s [len %d] %s" % (placeholder, len(placeholder), placeholder.transformedEntry))
                #if len(placeholder) > 0: print("- Its child: %s" % repr(placeholder[0][0].tail))
                #assert len(placeholder) == 0
                parent = elt.getparent()
                idx = parent.index(elt); assert idx >= 0
                te = placeholder.transformedEntry
                assert te is not None
                print("Transformed entry: %d %s" % (te.entryTime, te))
                print("Its parent: %s" % placeholder.transformedEntry.getparent())
                assert placeholder.transformedEntry.getparent() is None
                parent[idx] = placeholder.transformedEntry
                assert elt.getparent() is None
                assert placeholder.transformedEntry.getparent() is parent
        Rec(root)
    def BuildBody(self):
        # Builds a <body> element with the list of all top (i.e. non-nested) entries
        # (actually placeholders of transformed top entries).  Anything in between entries
        # in the original tree gets scrapified and included in the transformed entries.
        outBody = self.Element(ELT_body); self.outBody = outBody
        nTopEntries = len(self.topEntryList)
        #print("\n\n###### BuildBody")
        if nTopEntries == 0:
            print("Warning: no entries found.")
            outBody.append(self.SegifySubtree(self.tree.getroot()))
        else:
            nextLeft = self.ScrapifyLeft(self.topEntryList[0])
            tmStart = time.clock(); iPrev = 0; tmPrev = tmStart
            for i in range(nTopEntries):
                if (True or Verbose2) and i % 1000 == 0: 
                    tmNow = time.clock()
                    sys.stdout.write("BuildBody transforming entry %d/%d  (%.2f sec; %.2f entries/sec, recently %.2f)     \r" % (i, nTopEntries,
                        tmNow - tmStart, i / max(0.1, tmNow - tmStart), (i - iPrev) / max(0.1, tmNow - tmPrev))); sys.stdout.flush()
                    tmPrev = tmNow; iPrev = i    
                curLeft = nextLeft
                if i == nTopEntries - 1:
                    curRight = self.ScrapifyRight(self.topEntryList[i])
                else:
                    nextLeft, curRight = self.ScrapifyBetween(self.topEntryList[i], self.topEntryList[i + 1])
                inEntry = self.topEntryList[i]
                inEntry.tail = None # if there was a tail, it was already included in the curRight scrap
                outEntry = self.TransformEntry(inEntry).transformedEntry
                #print("i = %d, curLeft = %s, curRight = %s" % (i, curLeft, curRight))
                if curLeft is not None: 
                    assert not curLeft.tail
                    curLeft.tail = outEntry.text; outEntry.text = None
                    if curLeft.tag == ELT_seg: curLeft.tag = ELT_dictScrap
                    outEntry.insert(0, curLeft)
                    #print("outEntry = now %s" % outEntry)
                if curRight is not None: 
                    if curRight.tag == ELT_seg: curRight.tag = ELT_dictScrap
                    outEntry.append(curRight)
                outBody.append(outEntry)
        #return outBody
    def SetEntryLangs(self, root):
        # The xml:lang attribute of an <entry> might rely on something outside of that
        # entry's subtree in the input document, e.g. because it's inherited from a parent.
        # Thus we have to find and set the language here rather than from within
        # TEntryMapper, which gets the entry after it was detached from the tree.
        trOrders = {}; xf = self.m.xfEntryLang
        if xf:
            for trOrder in xf.findall(root):
                trOrders[id(trOrder.elt)] = trOrder
                SetMatchInfo(trOrder.elt, MATCH_entry_lang, trOrder.attr, trOrder.msFrom, trOrder.msTo)
        for elt in self.entryHash.values():
            langElt = elt; found = False
            while not (langElt is None):
                tr = trOrders.get(id(langElt), None)
                if tr and not (tr.matchedStr is None): found = True; break
                langElt = langElt.getparent()
            if not found: continue
            elt.xmlLangAttribute = tr.finalStr
    def Transform(self): # the main function
        verbose = True # Verbose2
        if verbose: print("Transform")
        oldRoot = self.tree.getroot()
        newRoot = self.InsertTempRoot(oldRoot)
        self.FindEntries(newRoot) # fills self.entryHash and self.eltHash
        if verbose: print("FindEntries found %d entries, %d elements." % (len(self.entryHash), len(self.eltHash)))
        self.MarkEntries() # fills self.topEntryList
        if verbose: print("MarkEntries found %d top-levelentries." % (len(self.topEntryList)))
        self.SetEntryLangs(newRoot) # sets the 'xmlLangAttribute' attribute of the entry Element objects
        if verbose: print("SetEntryLangs returned.")
        self.RemoveTempRoot(newRoot)
        if verbose: print("RemoveTempRoot returned.")
        self.TransformNonTopEntries()
        if verbose: print("TransformNonTopEntries returned.")
        self.BuildBody()  
        if verbose: print("BuildBody returned.")
        self.ReplacePlaceholders(self.outBody)  # replace placeholders with transformed entries
        if verbose: print("ReplacePlaceholders returned.")
        return self.outBody
        #print(etree.tostring(outTei, pretty_print = True).decode("utf8"))
        """
        if not self.relaxNg.validate(outTei):
            print("Relax-NG validation failed:\n%s" % (self.relaxNg.error_log))
        return outTei
        """
    def TestScrapify(self):    
        self.FindEntries(self.tree.getroot()) # fills self.entryHash and self.eltHash
        self.MarkEntries() # fills self.topEntryList
        scrap = self.ScrapifyLeft(self.topEntryList[0])
        print("Scrapified left!")
        print(etree.tostring(scrap, pretty_print = True).decode("utf8"))
        scrap = self.ScrapifyRight(self.topEntryList[-1])
        print("Scrapified right!")
        print(etree.tostring(scrap, pretty_print = True).decode("utf8"))
        print("Scrapified between!")
        (scrapL, scrapR) = self.ScrapifyBetween(self.topEntryList[0], self.topEntryList[1])
        print("- LEFT PART:")
        print("NULL" if scrapL is None else etree.tostring(scrapL, pretty_print = True).decode("utf8"))
        print("- RIGHT PART:")
        print("NULL" if scrapR is None else etree.tostring(scrapR, pretty_print = True).decode("utf8"))


class TMapper:
    __slots__ = [
        "relaxNg", # etree.RelaxNG
        "parser", # TXmlParser
    ]
    def __init__(self):
        parserLookup = etree.ElementDefaultClassLookup(element = TMyElement)
        self.parser = etree.XMLParser()
        self.parser.set_element_class_lookup(parserLookup)
        with open("./app/transformator/TEILex0-ODD.rng", "rt", encoding = "utf8") as f:
            relaxNgDoc = etree.parse(f)
        self.relaxNg = etree.RelaxNG(relaxNgDoc)
    def E(self, tag, attrib_ = {}, children = [], text = None, tail = None):
        e = self.parser.makeelement(tag, attrib = attrib_, nsmap = NS_MAP)
        for child in children: e.append(child)
        e.text = text; e.tail = tail
        return e
    def TransformTree(self, mapping, tree, outBody, outAugTrees):
        # Transforms 'tree' using a temporary instance of TTreeMapper and
        # moves the entries from its body into 'outBody'.
        makeAugTrees = outAugTrees is not None
        treeMapper = TTreeMapper(tree, mapping, self.parser, self.relaxNg, makeAugTrees)
        treeMapper.Transform()
        inBody = treeMapper.outBody; nElts = 0
        while len(inBody) > 0:
            elt = inBody[0]; inBody.remove(elt)
            outBody.append(elt)
            nElts += 1
        if makeAugTrees: 
            outAugTrees.append(treeMapper.augTree); treeMapper.augTree = None
        # ToDo: do something to force faster cleanup of 'treeMapper'?
        treeMapper.Clear()
        #print("TransformTree: %d elements transferred, %d now in outBody." % (nElts, len(outBody)))
    def StripForValidation(self, root):
        teiPref = "{%s}" % NS_TEI
        xmlPref = "{%s}" % NS_XML
        stats = {}
        def Rec(elt):
            if type(elt) is not TMyElement: return
            toDel = []
            for attrName in elt.keys():
                if not attrName.startswith("{"): continue
                if attrName.startswith(teiPref): continue
                if attrName.startswith(xmlPref): continue
                toDel.append(attrName); stats[attrName] = stats.get(attrName, 0) + 1
            for attrName in toDel: elt.attrib.pop(attrName)    
            for child in elt: Rec(child)
        Rec(root)
        if False:
            print("StripForValidation removed the following attributes:")
            for attrName in sorted(stats.keys()): print("%5d %s" % (stats[attrName], attrName))
    def StripDictScrap(self, root):
        def IsScrap(elt): return type(elt) is TMyElement and (elt.tag == ELT_seg or elt.tag == ELT_dictScrap)
        def Rec(elt):
            if type(elt) is not TMyElement: return
            isScrap = IsScrap(elt)
            if isScrap: elt.text = ""
            i = 0
            while i < len(elt):
                child = elt[i]
                if isScrap: child.tail = ""
                Rec(child)
                if IsScrap(child) and len(child) == 0:
                    if i == 0: AppendToText(elt, child.tail) 
                    else: AppendToTail(elt[i - 1], child.tail)
                    del elt[i]
                else: i += 1    
        Rec(root)        
    def FixIds(self, root):
        idHash = {}; counter = 0
        def Rec1(e):
            nonlocal idHash
            id_ = e.get(ATTR_ID)
            if id_ is None: return
            idHash[id_] = idHash.get(id_, 0) + 1
            for child in e: Rec1(child)
        def GenId(tag):
            nonlocal idHash, counter
            # We'll generate IDs of the form tag_number, where the tag
            # is stripped of any namespace prefixes.  The number will be
            # globally unique anyway.
            i = tag.find("}")
            if i >= 0: tag = tag[i + 1:]
            i = tag.find(":")
            if i >= 0: tag = tag[i + 1:]
            tag = tag.strip()
            if not tag: tag = "elt"
            while True:
                counter += 1
                cand = "%s_%s" % (tag, counter)
                if cand in idHash: continue
                idHash[cand] = 1
                return cand
        def Rec2(e):
            nonlocal idHash, counter
            id_ = e.get(ATTR_ID)
            needsId = False
            if id_ is not None and idHash.get(id_, 0) > 1: needsId = True
            elif e.tag == ELT_entry or e.tag == ELT_sense: needsId = True
            if needsId: e.set(ATTR_ID, GenId(e.tag))
            for child in e: Rec2(child)
        # Gather all the existing IDs into 'idHash' - though there shouldn't really be any
        # at this point, as we moved them to the meta namespace (ATTR_LEGACY_ID).
        Rec1(root) 
        # Now make sure that every <entry> and <sense> has an ID, and if any other
        # existing IDs weren't unique (due to the duplication of nodes etc.),
        # we'll fix this now.
        Rec2(root)    
    def GetFirstEntry(self, root):  
        if root.tag == ELT_entry: return root
        def Rec(node):
            for i in range(len(node)):
                child = node[i]
                if child.tag == ELT_entry:
                    if i == 0: AppendToText(node, child.tail)
                    else: AppendToTail(node[i - 1], child.tail)
                    child.tail = ""; del node[i]
                    #print("CHILD.nsmap = %s" % child.nsmap)
                    return child
                r = Rec(child)
                if r is not None: return r
        r = Rec(root)
        if r is None: return root
        else: return r
    def BuildHeader(self, metadata):
        """
        extent        -> teiHeader/fileDesc/extent
        bibl          -> teiHeader/fileDesc/sourceDesc/bibl
        source        -> teiHeader/fileDesc/sourceDesc/p
        
        title         -> teiHeader/fileDesc/titleStmt/title
        creator       -> each element gets a teiHeader/fileDesc/titleStmt/author
        contributor   -> each element gets a teiHeader/fileDesc/titleStmt/respStmt/name  + there's a respStmt/resp 

        publisher     -> teiHeader/fileDesc/publicationStmt/publisher
        license       -> teiHeader/fileDesc/publicationStmt/availability/licence
        created       -> teiHeader/fileDesc/publicationStmt/date  and its @when attribute
        identifier    -> teiHeader/fileDesc/publicationStmt/idno
        """
        # Note: <fileDesc> is required, and inside it <titleStmt>, <publicationStmt> and <sourceDesc> are all required.
        eltSourceDesc = self.E(ELT_sourceDesc, {}, [])
        # Inside <sourceDesc> we can have <bibl> and <p> with 'source'.
        hasSource = "source" in metadata; hasBibl = "bibl" in metadata
        eltBibl = self.E(ELT_bibl, {}, [], text = metadata.get("bibl", ""))
        if hasSource:
            # 'source' must go into a <p>, and we can't combine <p> and <bibl> inside <sourceDesc>
            # otherwise than by wrapping the <bibl> inside a <p>.
            if hasBibl: eltSourceDesc.append(self.E(ELT_p, {}, [eltBibl]))
            eltSourceDesc.append(self.E(ELT_p, {}, [], text = metadata.get("source", "")))
        elif hasBibl: eltSourceDesc.append(eltBibl)        # append a <bibl> if there's no 'source' in metadata
        else: eltSourceDesc.append(self.E(ELT_p, {}, []))  # <sourceDesc> requires something, at least an empty <p>
        # A <title> is required within <titleStmt>.
        eltTitleStmt = self.E(ELT_titleStmt, {}, [
            self.E(ELT_title, {}, [], text = metadata.get("title", ""))])
        def IsStr(x): return isinstance(x, str)
        def IsList(x): return isinstance(x, list)
        def IsDict(x): return isinstance(x, dict)
        def IsTuple(x): return isinstance(x, tuple)
        def GetAuthors(key):
            L = metadata.get(key, None)
            if L is None: return []
            if IsTuple(L) or IsStr(L): L = [L]
            L2 = []
            for author in L:
                if IsTuple(author): author = author[0]  # maybe it's a (name, eMail, url) triple
                elif IsDict(author): author = author.get("name", None) # maybe it's a dict with keys like "name" etc.
                if author: L2.append(author)
            return L2
        # The 'creator' list contributes <author> elements in the <titleStmt>.
        creators = GetAuthors("creator") + GetAuthors("creators")
        for creator in creators: eltTitleStmt.append(self.E(ELT_author, {}, [], text = str(creator)))
        # The 'contributor' list contributes <name> elements in a <respStmt> within the <titleStmt>.
        contribs = GetAuthors("contributor") + GetAuthors("contributors")
        eltRespStmt = None
        for contrib in contribs:
            if eltRespStmt is None: eltRespStmt = self.E(ELT_respStmt, {}, [
                self.E(ELT_resp, {}, [], text = "Made contributions to the dictionary")])
            eltRespStmt.append(self.E(ELT_name, {}, [], text = str(contrib))    )
        if eltRespStmt is not None: eltTitleStmt.append(eltRespStmt)
        # In the <publicationStmt>, we need something - at least an empty <p>.
        # If any details are provided -- i.e. <idno>, <date>, <availability>, they must be preceded
        # by a <publisher> or something like that.
        children = []
        if "licence" in metadata: children.append(self.E(ELT_availability, {}, [
            self.E(ELT_licence, {}, [], text = metadata.get("licence", ""))]))
        if "license" in metadata: children.append(self.E(ELT_availability, {}, [
            self.E(ELT_licence, {}, [], text = metadata.get("license", ""))]))
        if "created" in metadata: 
            when = metadata.get("created", "")
            children.append(self.E(ELT_date, {ATTR_when_UNPREFIXED: when}, [], text = when))
        if "identifier" in metadata: children.append(self.E(ELT_idno, {}, [], text = metadata.get("identifier", "")))
        hasPublisher = "publisher" in metadata
        if hasPublisher or children:
            children.insert(0, self.E(ELT_publisher, {}, [], text = metadata.get("publisher", "")))
        else: children.append(self.E(ELT_p, {}, []))
        eltPublicationStmt = self.E(ELT_publicationStmt, {}, children)
        # Now we can create a <fileDesc>.  <extent> must come after <titleStmt> but before <publicationStmt>.
        children = [eltTitleStmt]
        if "extent" in metadata: children.append(self.E(ELT_extent, {}, [], text = metadata.get("extent", "")))
        children += [eltPublicationStmt, eltSourceDesc]
        eltFileDesc = self.E(ELT_fileDesc, {}, children)
        # <extent> must come before <sourceDesc>.
        # Finally create the <teiHeader>.
        eltHeader = self.E(ELT_teiHeader, {}, [eltFileDesc])
        return eltHeader
    def Transform(self, mapping, fnOrFileList, treeList = [], makeAugmentedInputTrees = False, 
            stripForValidation = False, stripDictScrap = False, stripHeader = False,
            returnFirstEntryOnly = False,
            headerTitle = None, headerPublisher = None, headerBibl = None,
            metadata = None):
        """This method processes one or more XML trees and returns
        an (outTei, augTrees) pair, where outTei is the root <TEI> element 
        of the transformed output document, and augTrees is a list containing
        augmented copies of the input XML trees.  These augmented copies
        contain additional attributes that indicate which nodes were matched
        by which selectors and transformers from the given mapping.
        If makeAugmentedInputTree is False, no augmented trees are produced
        and augTrees will be None.

        To specify the input XML trees, use the 'fnOrFileList' and/or 'treeList' parameters.
        fnOrFileList can be either a single filename (as a string)
        or a list, each member of which must then be either a filename or a
        file-like object.  If a filename refers to a .zip file, all the
        files from that .zip file will be processed. 
        'treeList' should contain 0 or more lxml Element objects representing
        the roots of the trees to be processed.  

        The 'stripForValidation' parameter can be set to True to require that
        all the attributes from namespaces other than TEI and XML be stripped
        from the output document ('outTei').  This can be useful if the output
        is going to be validated against the TEI-lex-0 RelagNG schema.
        
        The 'stripDictScrap' parameter can be set to True to strip all <dictScrap>
        elements from the resulting output, and stripHeader can be set to True to
        strip the <teiHeader> element from the resulting output.
        
        The 'returnFirstEntryOnly' parameter can be set to True to return
        only the first <entry> element instead of the whole TEI XML document.
        """
        outBody = self.E(ELT_body)
        augTrees = [] if makeAugmentedInputTrees else None
        def ProcessFile(fn, f):
            print("Processing %s." % fn)
            tree = etree.ElementTree(file = f, parser = self.parser)
            print("Done parsing %s." % fn)
            self.TransformTree(mapping, tree, outBody, augTrees)
        print("stripHeader = %s, stripDictScrap = %s, stripForValidation = %s, returnFirstEntryOnly = %s" % (stripHeader,
            stripDictScrap, stripForValidation, returnFirstEntryOnly))    
        if type(fnOrFileList) is type(""): fnOrFileList = [fnOrFileList]    
        for fn in fnOrFileList:
            if type(fn) is not str:
                ProcessFile("<file-like-object>", fn)
            elif "*" in fn:
                for path in pathlib.Path(".").glob(fn):
                    with open(str(path), "rb") as f: ProcessFile(str(path), f)
            elif fn.lower().endswith(".zip"):
                with zipfile.ZipFile(fn, "r") as zf:
                    for fn2 in zf.namelist():
                        with zf.open(fn2, "r") as f: ProcessFile("%s[%s]" % (fn, fn2), f)
            else:
                with open(fn, "rb") as f: ProcessFile(fn, f)
        for tree in treeList: 
            self.TransformTree(mapping, tree, outBody, augTrees)
        if stripDictScrap: self.StripDictScrap(outBody)
        self.FixIds(outBody)    
        #            
        L = []
        if not stripHeader:
            if metadata is None: metadata = {}
            if headerTitle and "title" not in metadata: metadata["title"] = headerTitle
            if headerPublisher and "publisher" not in metadata: metadata["publisher"] = headerPublisher
            if headerBibl and "bibl" not in metadata: metadata["bibl"] = headerBibl
            L.append(self.BuildHeader(metadata))
            """
            # old version:
            L.append(self.E(ELT_teiHeader, {}, [
                self.E(ELT_fileDesc, {}, [
                    self.E(ELT_titleStmt, {}, [
                        self.E(ELT_title, {}, [], text = headerTitle)
                    ]),
                    self.E(ELT_publicationStmt, {}, [
                        self.E(ELT_publisher, {}, [], text = headerPublisher)
                    ]),
                    self.E(ELT_sourceDesc, {}, [
                        self.E(ELT_bibl, {}, [], text = headerBibl)
                    ]),
                ]),
            ]))
            """
        L.append(self.E(ELT_text, {}, [
                outBody
                #self.E(ELT_body, {}, [
                #    self.E("{%s}div" % NS_TEI, {}, [
                #        self.E("{%s}p" % NS_TEI, {}, [], text = "Foo"),
                #    ]),
                #]),
            ]))
        outTei = self.E(ELT_tei, {}, L)
        if returnFirstEntryOnly: 
            outTei = self.GetFirstEntry(outTei)
            x = self.E(outTei.tag, {}, [outTei[i] for i in range(len(outTei))])
            x.text = outTei.text
            outTei = x
            """
            print("NSMAP %s" % outTei.nsmap)
            outTei.nsmap[None] = NS_TEI
            del outTei.nsmap["ns0"]
            print("NSMAP %s" % outTei.nsmap)
            """
            #outTei = self.E(ELT_tei, {}, [outTei])
        #print(outBody.nsmap)
        #etree.cleanup_namespaces(outTei, top_nsmap = NS_MAP)
        #return outTei, augTrees
        if stripForValidation:
            self.StripForValidation(outTei)
            if not self.relaxNg.validate(outTei):
                print("Relax-NG validation failed:\n%s" % (self.relaxNg.error_log))
        return outTei, augTrees

def TestXpath():
    root = etree.fromstring("<root>foo<a>ena</a>dve<a>ena</a></root>")
    tree = etree.ElementTree(root)
    print(tree)
    def _(s): 
        n = 0
        for elt in tree.findall(s): n += 1
        print("%s -> %d matches" % (s, n))
    _(".//root")    
    
def TestHeader():
    items = [
        ("bibl", "This is a bibl."), 
        ("license", "An it harm none, do what thou wilt."), 
        ("title", "How to transform dictionaries and influence people"), 
        ("creator", ["First creator", "Second creator", "Third creator"]),
        ("publisher", "Random Mouse Publishers"), ("created", "2020-02-29"), 
        ("contributor", ["First contributor", "Second contributor"]), ("extent", "Absolutely massive"),
        ("identifier", "This one right here"), 
        ("source", "Fell from the sky")
        ]
    for bits in range(1 << len(items)):
        #if bits != (1 << len(items)) - 1: continue
        #if bits != 0: continue
        metadata = {}
        for i, (key, value) in enumerate(items):
            if ((bits >> i) & 1) == 0: continue
            metadata[key] = value
        mapper = TMapper()
        outTei, outAug = mapper.Transform(GetMcCraeTestMapping(), "WP1\\JMcCrae\\McC_xray.xml", makeAugmentedInputTrees = True, stripForValidation = True, metadata = metadata)
        f = open("transformed.xml", "wt", encoding = "utf8")
        f.write(etree.tostring(outTei, pretty_print = True, encoding = "utf8").decode("utf8"))
        f.close()
        if not mapper.relaxNg.validate(outTei):
            print("[%d] Relax-NG validation failed:\n%s" % (bits, mapper.relaxNg.error_log))
            sys.exit(0)


def Test():
    parserLookup = etree.ElementDefaultClassLookup(element = TMyElement)
    myParser = etree.XMLParser()
    myParser.set_element_class_lookup(parserLookup)
    #
    #f = open("WP1\\KD\\MLDS-FR-tralala.xml", "rt", encoding = "utf8")
    #f = open("toy01.xml", "rt", encoding = "Windows-1250")
    #f = open("toy02.xml", "rt", encoding = "Windows-1250")
    #f = open("toy03.xml", "rt", encoding = "Windows-1250")
    #f = open("toy04.xml", "rt", encoding = "Windows-1250")
    f = open("WP1\\JMcCrae\\McC_xray.xml", "rt", encoding = "utf8")
    tree = etree.ElementTree(file = f, parser = myParser)
    f.close()
    #
    #m = GetMldsMapping()
    #m = GetToyMapping()
    #m = GetMcCraeTestMapping()
    #mapper = TTreeMapper(tree, m, myParser)
    #outTei = mapper.Transform()
    mapper = TMapper()
    #outTei = mapper.Transform(m, ["WP1\\KD\\MLDS-FR-tralala.xml"])
    #f = open("mapping.json", "wt", encoding = "utf8")
    with open("mapping-MLDS.json", "wt", encoding = "utf8") as f: json.dump(GetMldsMapping().ToJson(), f, indent = 4)
    with open("mapping-ANW.json", "wt", encoding = "utf8") as f: json.dump(GetAnwMapping().ToJson(), f, indent = 4)
    with open("mapping-DDO.json", "wt", encoding = "utf8") as f: json.dump(GetDdoMapping().ToJson(), f, indent = 4)
    with open("mapping-SLD.json", "wt", encoding = "utf8") as f: json.dump(GetSldMapping().ToJson(), f, indent = 4)
    with open("mapping-SP.json", "wt", encoding = "utf8") as f: json.dump(GetSpMapping().ToJson(), f, indent = 4)
    #js = GetSldMapping().ToJson()
    #json.dump(js, f, indent = 4)
    #f.close()
    #m = TMapping(js)
    #outTei = mapper.Transform(m, ["WP1\\JSI\\SLD.zip"])
    #outTei = mapper.Transform(GetSldMapping(), ["WP1\\JSI\\SLD_macka_cat2.xml"])
    #outTei = mapper.Transform(GetSldMapping(), "WP1\\JSI\\SLD*.xml")
    #outTei, outAug = mapper.Transform(GetAnwMapping(), "WP1\\INT\\ANW*.xml")
    #outTei, outAug = mapper.Transform(GetAnwMapping(), "ANW_wijn_wine.xml", makeAugmentedInputTrees = True, stripForValidation = True)
    #outTei, outAug = mapper.Transform(GetDdoMapping(), "WP1\\DSL\\DSL samples\\DDO.xml", makeAugmentedInputTrees = True)
    #outTei, outAug = mapper.Transform(GetMldsMapping(), "WP1\\KD\\MLDS-FR.xml", makeAugmentedInputTrees = True, stripForValidation = True)
    #outTei, outAug = mapper.Transform(GetSpMapping(), "WP1\\JSI\\SP2001.xml", makeAugmentedInputTrees = True, stripForValidation = True)
    outTei, outAug = mapper.Transform(GetMcCraeTestMapping(), "WP1\\JMcCrae\\McC_xray.xml", makeAugmentedInputTrees = True, stripForValidation = False)
    f = open("transformed.xml", "wt", encoding = "utf8")
    # encoding="utf8" is important when calling etree.tostring, otherwise
    # it represents non-ascii characters in attribute names with entities,
    # which is invalid XML.
    f.write(etree.tostring(outTei, pretty_print = True, encoding = "utf8").decode("utf8"))
    f.close()
    f = open("augmented-input.xml", "wt", encoding = "utf8")
    f.write(etree.tostring(outAug[0], pretty_print = True, encoding = "utf8").decode("utf8"))
    f.close()

#TestHeader()
#TestXpath()
#Test(); sys.exit(0)

# ToDo: use the defusedxml library


WsgiOutPath = "d:\\users\\janez\\data\\Elexis\\TransformDemo"

def MyWsgiHandler(env, start_response):
    print("FOO")
    def Err(s, status = "error"): js = {"status": status, "errDesc": s}; return [json.dumps(js, ensure_ascii = True)]
    started = False
    t = datetime.datetime.utcnow()
    outPath = os.path.join(WsgiOutPath, "%04d-%02d-%02d-%02d-%02d-%02d-%03d-%s" % (
        t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond // 1000, 
        env.get("REMOTE_HOST", env.get("REMOTE_ADDR", ""))))
    try: os.mkdir(outPath)
    except: pass
    try:
        requestMethod = env.get("REQUEST_METHOD", "")
        body = ""
        if requestMethod == "POST":
            f = env.get("wsgi.input")
            if f: body = f.read()
            #f.close()
        queryString = env.get("QUERY_STRING", "")
        print("Request method = %s;  queryString = %s,  request body = %s" % (
            repr(requestMethod), repr(queryString[:50]), repr(body[:50])))
        params = urllib_parse.parse_qs("&".join([queryString, body.decode("utf8")]))
        def GetArg(name, defaultValue = u""):
            if name not in params: return defaultValue
            L = params[name]
            if type(L) is type([]): s = L[0]
            else: s = str(L)
            return s
        def TransferArg(name):
            if name not in params: return
            L = params[name]
            if type(L) is type([]): s = L[0]
            else: s = str(L)
            callParams[name] = s
        #start_response("200 OK", [("Content-type", "application/json")])
        #textPlain = (GetArg("textPlain", "false") == "true")
        mappingStr = GetArg("mapping")
        inputStr = GetArg("input")
        callParams = {}
        callParams["stripForValidation"] = (GetArg("stripForValidation") == "true")
        callParams["stripDictScrap"] = (GetArg("stripDictScrap") == "true")
        callParams["stripHeader"] = (GetArg("stripHeader") == "true")
        callParams["returnFirstEntryOnly"] = (GetArg("firstEntryOnly") == "true")
        TransferArg("headerTitle"); TransferArg("headerPublisher"); TransferArg("headerBibl")
        for name in params: print("param %s" % repr(name))
        #print("stripForValidation = %s" % GetArg("stripForValidation"))
        with open(os.path.join(outPath, "mapping.json"), "wt", encoding = "utf8") as f: f.write(mappingStr) #; f.write(str(env))
        with open(os.path.join(outPath, "input.xml"), "wt", encoding = "utf8") as f: f.write(inputStr)
        #
        mapper = TMapper()
        mappingJs = json.loads(mappingStr)
        with io.BytesIO(inputStr.encode("utf8")) as f:
            inputXml = etree.ElementTree(file = f, parser = mapper.parser)
        mapping = TMapping(mappingJs)
        outputXml, augTrees = mapper.Transform(mapping, [], [inputXml], **callParams)
        #
        outputBin = etree.tostring(outputXml, pretty_print = True, encoding = "utf8")
        with open(os.path.join(outPath, "output.xml"), "wb") as f: f.write(outputBin)
        #
        start_response("200 OK", [("Content-type", "text/xml")])
        started = True
        return [outputBin]
    except:
        errDesc = "".join(traceback.format_exception(*sys.exc_info()))
        sys.stdout.write(errDesc); sys.stdout.flush()
        with open(os.path.join(outPath, "error.txt"), "wt", encoding = "utf8") as f: f.write(errDesc)
        if not started:
            try: start_response("200 OK", [("Content-type", "text/plain")])
            except: pass
        #return Err(errDesc, "exception")
        return errDesc
        
if "--runserver" in sys.argv or "--runServer" in sys.argv:
    wsgi.server(eventlet.listen(("localhost", 8101)), MyWsgiHandler)
    sys.exit(0)

"""
ToDo:
[OK] - TMapper.Transform naj vrne tudi obogateno razlicico vhodnega XMLja,
  v katero smo dodali nekaj meta atributov: pri elementih, ki so se pomatchali
  z nekim selektorjem, naj to pise (in za kateri output element je to bilo: sense, hw, ex itd.);
  pise naj tudi, kateri atribut je bil uporabljen in mogoce zacetni/koncni index v primeru regex matcha;
  poleg tega pa naj Transform vrne za vsak output element tudi seznam uspesno izvedenih
  transformacij, v katerem bodo pari (vrednost selectanega atributa pred regexom,
  vrednost po regexu).
[OK] - Ko razbijemo <cit> na <cit> in <quote>, je treba atribut type pustiti v <cit>.  
"""