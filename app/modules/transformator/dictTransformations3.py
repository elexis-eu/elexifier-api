# coding=Windows-1250
#import xml.etree, xml.etree.ElementTree
from lxml import etree
import copy, re, logging, traceback, zipfile, json, pathlib, eventlet, sys, datetime, os, os.path, io, time, codecs, re
from eventlet import wsgi
urllib_parse = eventlet.import_patched("urllib.parse")
urllib_request = eventlet.import_patched("urllib.request")
urllib_error = eventlet.import_patched("urllib.error")

logging.basicConfig(format = "[%(asctime)s] [%(levelname)s] %(message)s", level = logging.DEBUG)

Verbose = False
Verbose2 = False

class TXpathSelector:
    __slots__ = ["expr"]
    def __init__(self, expr):
        self.expr = expr
    def findall(self, tree):
        #print("\ntree = %s %s, expr = %s" % (type(tree), etree.tostring(tree, pretty_print=True), self.expr))
        #if type(tree) is not TMyElement: tree = tree.getroot()
        #for x in tree.findall(self.expr): yield x
        for x in tree.xpath(self.expr): yield x
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

def AppendToText(node, what, addSpace = False):
    if node is None: return
    if what is None or what == "": return
    if node.text is None: node.text = what
    else: 
        if addSpace:
            if node.text and node.text[-1].isspace(): pass
            elif what and what[0].isspace(): pass
            else: node.text += " "
        node.text += what

def AppendToTail(node, what, addSpace = False):
    if node is None: return
    if what is None or what == "": return
    tail = node.tail or ""
    if addSpace:
        if tail and tail[-1].isspace(): pass
        elif what and what[0].isspace(): pass
        else: tail += " "
    node.tail = tail + what

def EltToStr(elt):
    if elt is None: return ""
    tag = elt.tag
    i = tag.rfind('}')
    if i >= 0: tag = tag[i + 1:]
    s = "<%s>%s%s</%s>%s" % (tag, "" if elt.text is None else elt.text, "".join(EltToStr(child) for child in elt), tag, "" if elt.tail is None else elt.tail)
    s = s.replace('\n', ' ').replace('\t', ' ').replace('\r',  ' ').strip()
    while "  " in s: s = s.replace("  ", " ")
    return s

def GetFirstChild(x):
    for child in x: return child
    return None

# Removes elt from the tree, but inserts its children between elt's former previous and next sibling.
def RemoveElementAndPromoteChildren(elt, appendSpace):
    parent = elt.getparent()
    assert parent is not None
    prevSib = elt.getprevious(); nextSib = elt.getnext()
    if prevSib is None: AppendToText(parent, elt.text, appendSpace)
    else: AppendToTail(prevSib, elt.text, appendSpace)
    oldTail = elt.tail
    parent.remove(elt)
    newTail = elt.tail
    assert oldTail == newTail
    for child in elt:
        if prevSib is not None: prevSib.addnext(child)
        elif nextSib is not None: nextSib.addprevious(child)
        else: parent.append(child)
        prevSib = child
    s = elt.tail or ""
    if appendSpace and nextSib is not None and s and not s[-1].isspace(): s += " "
    if prevSib is None: AppendToText(parent, s, appendSpace)
    else: AppendToTail(prevSib, s, appendSpace)

# The following two are according to the XML spec.
# https://www.w3.org/TR/xml/#NT-Name
"""
def IsNameStartChar(x):
    return (x == 0x3a or 0x41 <= x <= 0x5a or x == 0x5f or 0x61 <= x <= 0x7a or 0xc0 <= x <= 0xd6 or
        0xd8 <= x <= 0xf6 or 0xf8 <= x <= 0x2ff or 0x370 <= x <= 0x37d or 0x37f <= x <= 0x1fff or
        0x200c <= x <= 0x200d or 0x2070 <= x <= 0x218f or 0x2c00 <= x <= 0x2fef or 0x3001 <= x <= 0xd7ff or
        0xf900 <= x <= 0xfdcf or 0xfdf0 <= x <= 0xfffd or 0x10000 <= x <= 0xeffff)
def IsNameChar(x):
    return (x == 0x2d or x == 0x2e or 0x30 <= x <= 0x39 or x == 0x3a or 0x41 <= x <= 0x5a or x == 0x5f or 0x61 <= x <= 0x7a or x == 0xb7 or 0xc0 <= x <= 0xd6 or
        0xd8 <= x <= 0xf6 or 0xf8 <= x <= 0x2ff or 0x300 <= x <= 0x36f or 0x370 <= x <= 0x37d or 0x37f <= x <= 0x1fff or
        0x200c <= x <= 0x200d or 0x203f <= x <= 0x2040 or 0x2070 <= x <= 0x218f or 0x2c00 <= x <= 0x2fef or 0x3001 <= x <= 0xd7ff or
        0xf900 <= x <= 0xfdcf or 0xfdf0 <= x <= 0xfffd or 0x10000 <= x <= 0xeffff)
"""
# However, the jing/trang validator for relax-ng allows a narrower set of characters.
# https://github.com/relaxng/jing-trang/blob/12275d143f855834919e53174be4ce2040e2f913/mod/util/src/main/com/thaiopensource/xml/util/Naming.java#L109        
nameStartSingles = (
  "\u003a\u005f\u0386\u038c\u03da\u03dc\u03de\u03e0\u0559\u06d5\u093d\u09b2" +
  "\u0a5e\u0a8d\u0abd\u0ae0\u0b3d\u0b9c\u0cde\u0e30\u0e84\u0e8a\u0e8d\u0ea5" +
  "\u0ea7\u0eb0\u0ebd\u1100\u1109\u113c\u113e\u1140\u114c\u114e\u1150\u1159" +
  "\u1163\u1165\u1167\u1169\u1175\u119e\u11a8\u11ab\u11ba\u11eb\u11f0\u11f9" +
  "\u1f59\u1f5b\u1f5d\u1fbe\u2126\u212e\u3007")
nameStartRanges = (
  "\u0041\u005a\u0061\u007a\u00c0\u00d6\u00d8\u00f6\u00f8\u00ff\u0100\u0131" +
  "\u0134\u013e\u0141\u0148\u014a\u017e\u0180\u01c3\u01cd\u01f0\u01f4\u01f5" +
  "\u01fa\u0217\u0250\u02a8\u02bb\u02c1\u0388\u038a\u038e\u03a1\u03a3\u03ce" +
  "\u03d0\u03d6\u03e2\u03f3\u0401\u040c\u040e\u044f\u0451\u045c\u045e\u0481" +
  "\u0490\u04c4\u04c7\u04c8\u04cb\u04cc\u04d0\u04eb\u04ee\u04f5\u04f8\u04f9" +
  "\u0531\u0556\u0561\u0586\u05d0\u05ea\u05f0\u05f2\u0621\u063a\u0641\u064a" +
  "\u0671\u06b7\u06ba\u06be\u06c0\u06ce\u06d0\u06d3\u06e5\u06e6\u0905\u0939" +
  "\u0958\u0961\u0985\u098c\u098f\u0990\u0993\u09a8\u09aa\u09b0\u09b6\u09b9" +
  "\u09dc\u09dd\u09df\u09e1\u09f0\u09f1\u0a05\u0a0a\u0a0f\u0a10\u0a13\u0a28" +
  "\u0a2a\u0a30\u0a32\u0a33\u0a35\u0a36\u0a38\u0a39\u0a59\u0a5c\u0a72\u0a74" +
  "\u0a85\u0a8b\u0a8f\u0a91\u0a93\u0aa8\u0aaa\u0ab0\u0ab2\u0ab3\u0ab5\u0ab9" +
  "\u0b05\u0b0c\u0b0f\u0b10\u0b13\u0b28\u0b2a\u0b30\u0b32\u0b33\u0b36\u0b39" +
  "\u0b5c\u0b5d\u0b5f\u0b61\u0b85\u0b8a\u0b8e\u0b90\u0b92\u0b95\u0b99\u0b9a" +
  "\u0b9e\u0b9f\u0ba3\u0ba4\u0ba8\u0baa\u0bae\u0bb5\u0bb7\u0bb9\u0c05\u0c0c" +
  "\u0c0e\u0c10\u0c12\u0c28\u0c2a\u0c33\u0c35\u0c39\u0c60\u0c61\u0c85\u0c8c" +
  "\u0c8e\u0c90\u0c92\u0ca8\u0caa\u0cb3\u0cb5\u0cb9\u0ce0\u0ce1\u0d05\u0d0c" +
  "\u0d0e\u0d10\u0d12\u0d28\u0d2a\u0d39\u0d60\u0d61\u0e01\u0e2e\u0e32\u0e33" +
  "\u0e40\u0e45\u0e81\u0e82\u0e87\u0e88\u0e94\u0e97\u0e99\u0e9f\u0ea1\u0ea3" +
  "\u0eaa\u0eab\u0ead\u0eae\u0eb2\u0eb3\u0ec0\u0ec4\u0f40\u0f47\u0f49\u0f69" +
  "\u10a0\u10c5\u10d0\u10f6\u1102\u1103\u1105\u1107\u110b\u110c\u110e\u1112" +
  "\u1154\u1155\u115f\u1161\u116d\u116e\u1172\u1173\u11ae\u11af\u11b7\u11b8" +
  "\u11bc\u11c2\u1e00\u1e9b\u1ea0\u1ef9\u1f00\u1f15\u1f18\u1f1d\u1f20\u1f45" +
  "\u1f48\u1f4d\u1f50\u1f57\u1f5f\u1f7d\u1f80\u1fb4\u1fb6\u1fbc\u1fc2\u1fc4" +
  "\u1fc6\u1fcc\u1fd0\u1fd3\u1fd6\u1fdb\u1fe0\u1fec\u1ff2\u1ff4\u1ff6\u1ffc" +
  "\u212a\u212b\u2180\u2182\u3041\u3094\u30a1\u30fa\u3105\u312c\uac00\ud7a3" +
  "\u4e00\u9fa5\u3021\u3029")
nameSingles = (
  "\u002d\u002e\u05bf\u05c4\u0670\u093c\u094d\u09bc\u09be\u09bf\u09d7\u0a02" +
  "\u0a3c\u0a3e\u0a3f\u0abc\u0b3c\u0bd7\u0d57\u0e31\u0eb1\u0f35\u0f37\u0f39" +
  "\u0f3e\u0f3f\u0f97\u0fb9\u20e1\u3099\u309a\u00b7\u02d0\u02d1\u0387\u0640" +
  "\u0e46\u0ec6\u3005")
nameRanges = (
  "\u0300\u0345\u0360\u0361\u0483\u0486\u0591\u05a1\u05a3\u05b9\u05bb\u05bd" +
  "\u05c1\u05c2\u064b\u0652\u06d6\u06dc\u06dd\u06df\u06e0\u06e4\u06e7\u06e8" +
  "\u06ea\u06ed\u0901\u0903\u093e\u094c\u0951\u0954\u0962\u0963\u0981\u0983" +
  "\u09c0\u09c4\u09c7\u09c8\u09cb\u09cd\u09e2\u09e3\u0a40\u0a42\u0a47\u0a48" +
  "\u0a4b\u0a4d\u0a70\u0a71\u0a81\u0a83\u0abe\u0ac5\u0ac7\u0ac9\u0acb\u0acd" +
  "\u0b01\u0b03\u0b3e\u0b43\u0b47\u0b48\u0b4b\u0b4d\u0b56\u0b57\u0b82\u0b83" +
  "\u0bbe\u0bc2\u0bc6\u0bc8\u0bca\u0bcd\u0c01\u0c03\u0c3e\u0c44\u0c46\u0c48" +
  "\u0c4a\u0c4d\u0c55\u0c56\u0c82\u0c83\u0cbe\u0cc4\u0cc6\u0cc8\u0cca\u0ccd" +
  "\u0cd5\u0cd6\u0d02\u0d03\u0d3e\u0d43\u0d46\u0d48\u0d4a\u0d4d\u0e34\u0e3a" +
  "\u0e47\u0e4e\u0eb4\u0eb9\u0ebb\u0ebc\u0ec8\u0ecd\u0f18\u0f19\u0f71\u0f84" +
  "\u0f86\u0f8b\u0f90\u0f95\u0f99\u0fad\u0fb1\u0fb7\u20d0\u20dc\u302a\u302f" +
  "\u0030\u0039\u0660\u0669\u06f0\u06f9\u0966\u096f\u09e6\u09ef\u0a66\u0a6f" +
  "\u0ae6\u0aef\u0b66\u0b6f\u0be7\u0bef\u0c66\u0c6f\u0ce6\u0cef\u0d66\u0d6f" +
  "\u0e50\u0e59\u0ed0\u0ed9\u0f20\u0f29\u3031\u3035\u309d\u309e\u30fc\u30fe")
class TIdFixer:
    __slots__ = ["cache", "atStart", "nameStartChars", "nameChars"]
    def InitBitfield(self, L, singles, ranges):
        for c in singles: L[ord(c)] = True 
        for i in range(len(ranges) // 2):
            cFrom = ord(ranges[2 * i]); cTo = ord(ranges[2 * i + 1])
            for x in range(cFrom, cTo + 1): L[x] = True
    def __init__(self, atStart): 
        self.cache = {}; self.atStart = atStart
        self.nameStartChars = [False] * 65536
        self.InitBitfield(self.nameStartChars, nameStartSingles, nameStartRanges)
        self.nameChars = self.nameStartChars[:]
        self.InitBitfield(self.nameChars, nameSingles, nameRanges)
    # Checks if s is a valid sequence of XML name characters (if self.atStart is true,
    # it also checks if the first character of s is an XML name start character).
    # If this is the case, it returns s; otherwise, it returns a string obtained by
    # replacing any invalid characters in s by the sequence U+3007 + hex code of the
    # offending character + U+3007.  (Note that U+3007, the ideographic number 0, is a valid
    # name start character).
    def Fix(self, s):
        s = re.sub("\\s+", ".", s.strip())
        t = self.cache.get(s)
        if t is not None: return t
        L = []; first = True
        for c in s:
            x = ord(c)
            ok = (x != 0x3a) and (x <= 0xffff) and (self.nameStartChars[x] if first and self.atStart else self.nameChars[x])
            if ok and c != 0x3007: L.append(c)
            else: L.append("\u3007%x\u3007" % x)
        t = "".join(L); self.cache[s] = t; return t

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
        logging.info("TransformOrder for <%s>, rex %s, matched %s -> %s, inserted %d start and %d end milestones." % (
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
ATTR_META_POS_FOR_ID = "{%s}posForId" % NS_META
ATTR_META_HEADWORD_FOR_ID = "{%s}hwForId" % NS_META
ATTR_orig_UNPREFIXED = "orig"
#ATTR_type = "{%s}%s" % (NS_TEI, ATTR_type_UNPREFIXED)
ATTR_MATCH = "{%s}match" % NS_META
ATTR_MATCH_ATTR = "{%s}matchAttr" % NS_META
ATTR_MATCH_FROM = "{%s}matchFrom" % NS_META
ATTR_MATCH_TO = "{%s}matchTo" % NS_META
ELT_ENTRY_PLACEHOLDER = "{%s}entryPlaceholder" % NS_META
ATTR_PLACEHOLDER_ID = "{%s}placeholderId" % NS_META
ELT_MILESTONE = "{%s}milestone" % NS_META
ELT_TEMP_ROOT = "{%s}tempRoot" % NS_META
#ELT_PHASE_2_STUB = "{%s}phase2Stub" % NS_META
ELT_dictScrap = "{%s}dictScrap" % NS_TEI
ELT_seg = "{%s}seg" % NS_TEI
ELT_orth = "{%s}orth" % NS_TEI
ELT_form = "{%s}form" % NS_TEI
ELT_cit = "{%s}cit" % NS_TEI
ELT_quote = "{%s}quote" % NS_TEI
ELT_note = "{%s}note" % NS_TEI
ELT_gloss = "{%s}gloss" % NS_TEI
ELT_usg = "{%s}usg" % NS_TEI
ELT_xr = "{%s}xr" % NS_TEI
ELT_ref = "{%s}ref" % NS_TEI
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
ELT_PSEUDO_text = "{%s}cdata" % NS_META
CommentType = type(etree.Comment(""))

MATCH_entry = "entry"
MATCH_entry_lang = "entry_lang"
MATCH_hw = "hw"
MATCH_lemma = "lemma"
MATCH_inflected = "inflected"
MATCH_variant = "variant"
MATCH_sense = "sense"
MATCH_def = "def"
MATCH_pos = "pos"
MATCH_hw_tr = "hw_tr"
MATCH_hw_tr_lang = "hw_tr_lang"
MATCH_ex = "ex"
MATCH_ex_tr = "ex_tr"
MATCH_ex_tr_lang = "ex_tr_lang"
MATCH_gloss = "gloss"
MATCH_usg = "usg"
MATCH_xr = "xr"
MATCH_note = "note"

def IsScrap(elt): return elt is not None and type(elt) is TMyElement and (elt.tag == ELT_seg or elt.tag == ELT_dictScrap)

class TMapping:
    #
    __slots__ = [
        "selEntry",      # becomes <entry>
        # - The rest is relative to the entry.
        "xfHw",  # headword; becomes <form type="lemma"><orth>
        "xfLemma",  # headword; becomes <form type="simple"><orth>
        "xfVariant",  # variant headword; becomes <form type="variant"><orth>
        "xfInflected",  # inflected form; becomes <form type="inflected"><orth>
        "selSense",  # becomes <sense>  
        "xfEntryLang", # becomes @xml:lang of <entry>
        "xfDef",  # definition; becomes <def>
        "xfPos",  # part-of-speech; becomes <gram type="pos">
        "xfHwTr", # translated headword; becomes <cit type="translationEquivalent">
        "xfNote", # note; becomes <note>
        "xfUsg", # label; becomes <usg type="hint">
        "xfXr", # cross-reference; becomes <xr type="related">
        "xfGloss", # sense indicator; becomes <gloss>
        "xfHwTrLang",  # language of the translated headword [goes into the xml:lang attribute]
        "xfEx", # example; becomes <cit type="example"><quote>
        "xfExTr", # translated example; becomes <cit type="translation">
        "xfExTrLang",  # language of the translated example [goes into the xml:lang attribute]
    ]
    def __init__(self, js = None):
        self.selEntry = None; self.xfEntryLang = None
        self.xfHw = None; self.xfLemma = None; self.selSense = None
        self.xfVariant = None; self.xfInflected = None
        self.xfPos = None; self.xfHwTr = None; self.xfHwTrLang = None
        self.xfEx = None; self.xfExTr = None; self.xfExTrLang = None
        self.xfDef = None; self.xfNote = None; self.xfUsg = None; self.xfGloss = None; self.xfXr = None
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
        _("variant", self.xfVariant)
        _("inflected", self.xfInflected)
        _("hw_tr", self.xfHwTr)
        _("hw_tr_lang", self.xfHwTrLang)
        _("ex", self.xfEx)
        _("ex_tr", self.xfExTr)
        _("ex_tr_lang", self.xfExTrLang)
        _("def", self.xfDef)
        _("note", self.xfNote)
        _("usg", self.xfUsg)
        _("xr", self.xfXr)
        _("gloss", self.xfGloss)
        return h
    def InitFromJson(self, h):
        self.selEntry = JsonToSelector(h.get("entry", None))
        self.selSense = JsonToSelector(h.get("sense", None))
        self.xfDef = JsonToTransformer(h.get("def", None))
        self.xfPos = JsonToTransformer(h.get("pos", None))
        self.xfHw = JsonToTransformer(h.get("hw", None))
        self.xfLemma = JsonToTransformer(h.get("sec_hw", None))
        self.xfVariant = JsonToTransformer(h.get("variant", None))
        self.xfInflected = JsonToTransformer(h.get("inflected", None))
        self.xfHwTr = JsonToTransformer(h.get("hw_tr", None))
        self.xfHwTrLang = JsonToTransformer(h.get("hw_tr_lang", None))
        self.xfEx = JsonToTransformer(h.get("ex", None))
        self.xfExTr = JsonToTransformer(h.get("ex_tr", None))
        self.xfExTrLang = JsonToTransformer(h.get("ex_tr_lang", None))
        self.xfEntryLang = JsonToTransformer(h.get("entry_lang", None))
        self.xfNote = JsonToTransformer(h.get("note", None))
        self.xfUsg = JsonToTransformer(h.get("usg", None))
        self.xfXr = JsonToTransformer(h.get("xr", None))
        self.xfGloss = JsonToTransformer(h.get("gloss", None))

def GetFromLexonomyMapping():
    m = TMapping()
    m.selEntry = TXpathSelector(".//container[@name='entry']")
    m.xfEntryLang = TSimpleTransformer(TXpathSelector(".//container[@name='entry']"), ATTR_CONSTANT, constValue = "sl")
    m.xfHw = TSimpleTransformer(TXpathSelector(".//container[@name='headword']"), ATTR_INNER_TEXT_REC)
    m.xfPos = TSimpleTransformer(TXpathSelector(".//container[@name='pos']"), ATTR_INNER_TEXT_REC)
    m.xfHwTr = TSimpleTransformer(TXpathSelector(".//container[@name='translation']"), ATTR_INNER_TEXT_REC)
    m.xfHwTrLang = TSimpleTransformer(TXpathSelector(".//container[@name='translation']"), ATTR_CONSTANT, constValue = "en")
    return m

def GetMldsMapping():
    m = TMapping()
    m.selEntry = TUnionSelector([
        TXpathSelector("Entry"), TXpathSelector(".//DictionaryEntry")])
    m.xfEntryLang = TSimpleTransformer(
        TXpathSelector("Dictionary"), "sourceLanguage")
    #m.xfHw = TSimpleTransformer(TXpathSelector(".//Headword"), ATTR_INNER_TEXT)
    m.xfHw = TSimpleTransformer(TXpathSelector(".//ancestor::Entry"), "hw")
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
    m.xfEntryLang = TSimpleTransformer(TXpathSelector("."),
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
    if True: m.selEntry = TUnionSelector([
        TXpathSelector(".//artikel"),
        TXpathSelector(".//Verbindingen")])
    m.xfEntryLang = TSimpleTransformer(TXpathSelector(".//artikel"),
        ATTR_CONSTANT, constValue = "nl")
    m.xfHw = TSimpleTransformer(TXpathSelector(".//Lemmavorm"), ATTR_INNER_TEXT_REC)
    m.xfVariant = TSimpleTransformer(TXpathSelector(".//Synoniem//lemma"), ATTR_INNER_TEXT_REC)    
    m.xfInflected = TSimpleTransformer(TXpathSelector(".//SpellingEnFlexie//Woordvorm"), ATTR_INNER_TEXT_REC)    
    m.selSense = TXpathSelector(".//Kernbetekenis")
    m.xfDef = TSimpleTransformer(TXpathSelector(".//Definitie"), ATTR_INNER_TEXT_REC)
    m.xfPos = TSimpleTransformer(TXpathSelector(".//Woordsoort/Type"), ATTR_INNER_TEXT,
        xlat = {"substantief": "noun"})
    m.xfHwTr = None
    m.xfHwTrLang = None
    m.xfEx = TSimpleTransformer(TXpathSelector(".//Voorbeeld/Tekst"), ATTR_INNER_TEXT_REC)
    m.xfExTr = None
    m.xfExTrLang = None
    m.xfGloss = TSimpleTransformer(TXpathSelector(".//Uiterlijk"), ATTR_INNER_TEXT_REC)
    m.xfNote = TSimpleTransformer(TXpathSelector(".//Realisatie"), ATTR_INNER_TEXT_REC)
    m.xfXr = TSimpleTransformer(TXpathSelector(".//pid"), ATTR_INNER_TEXT_REC)
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

def GetHwnMapping():
    m = TMapping()
    m.selEntry = TXpathSelector(".//synonym")
    m.xfEntryLang = TSimpleTransformer(TXpathSelector(".//synonym"), ATTR_CONSTANT, constValue = "he")
    m.xfHw = TSimpleTransformer(TXpathSelector(".//lemma"), ATTR_INNER_TEXT_REC)
    #m.xfDef = TSimpleTransformer(TXpathSelector(".//gloss"), ATTR_INNER_TEXT_REC) 
    #m.selSense = TXpathSelector(".//synonym")
    #m.xfPos = TSimpleTransformer(TXpathSelector(".//synset"), "pos")
    m.xfPos = TSimpleTransformer(TXpathSelector(".."), "pos")
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

def MakeAcronym(s):
    words = (s or "").strip().split()
    initials = []
    for word in words:
        for c in word:
            if c.isalpha(): initials.append(c.upper()); break
    acronym = "".join(initials) or "dict"
    return acronym

# This assumes that the form/orth pair is represented by orth, gramGrp/gram by gram, cit/quote by cit.
# Also note that this hash table is used in stage 2, when <orth> elements are still
# actually temporary <orthHw> and <orthLemma> - they will be renamed in stage 3.
# Another problem here is that <usg> may be a child of <gramGrp> but not of <gram>,
# so the fact that we only see <gram> at that point may lead us to move <usg> too high up.
allowedParentHash = {
    ELT_seg: set([ELT_seg, ELT_entry, ELT_orth, ELT_def, ELT_gram, ELT_cit, ELT_dictScrap, ELT_sense, ELT_usg, ELT_gloss, ELT_note, ELT_xr]),
    ELT_ref: set([ELT_seg, ELT_entry, ELT_orth, ELT_def, ELT_gram, ELT_cit, ELT_dictScrap, ELT_sense, ELT_usg, ELT_gloss, ELT_note, ELT_xr]),
    ELT_def: set([ELT_sense, ELT_dictScrap]),
    ELT_orth: set([ELT_sense, ELT_dictScrap, ELT_entry]),
    ELT_gram: set([ELT_sense, ELT_dictScrap, ELT_entry]),
    ELT_cit: set([ELT_sense, ELT_dictScrap, ELT_entry, ELT_cit, ELT_seg, ELT_usg, ELT_gloss, ELT_note, ELT_xr]),
    ELT_sense: set([ELT_sense, ELT_dictScrap, ELT_entry]),
    ELT_entry: set([ELT_entry]),
    ELT_ENTRY_PLACEHOLDER: set([ELT_entry]),
    ELT_dictScrap: set([ELT_entry, ELT_dictScrap]),
    ELT_note: set([ELT_gloss, ELT_cit, ELT_note, ELT_quote, ELT_def, ELT_dictScrap, ELT_entry, ELT_form, ELT_gram, ELT_gramGrp, ELT_orth, ELT_usg, ELT_seg, ELT_xr]),
    ELT_gloss: set([ELT_cit, ELT_gloss, ELT_note, ELT_quote, ELT_def, ELT_dictScrap, ELT_form, ELT_gram, ELT_gramGrp, ELT_orth, ELT_sense, ELT_usg, ELT_seg, ELT_xr]),
    ELT_usg: set([ELT_dictScrap, ELT_entry, ELT_form, ELT_gramGrp, ELT_sense]),
    ELT_xr: set([ELT_cit, ELT_gloss, ELT_note, ELT_gram, ELT_gramGrp, ELT_def, ELT_dictScrap, ELT_entry, ELT_orth, ELT_sense, ELT_xr, ELT_seg]),
    # The following entry is used to indicate which elements may contain text (character data) directly.
    # This is used by StripDictScrap().
    ELT_PSEUDO_text: set([ELT_seg, ELT_def, ELT_orth, ELT_gram, ELT_dictScrap, ELT_note, ELT_gloss, ELT_usg, ELT_gramGrp])  # but not entry, sense, cit, xr
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
#      at the end by wrapping it into a <dictScrap>.
#      Note2: at some point they removed <def> from model.entryPart, which means that
#      <def> can no longer be a child of <dictScrap> either.  The only solution now
#      is to wrap such a <def> into a <sense>. 
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
        "senseIds", "nestedEntriesWillBePromoted",
        "mDef", "mPos", "mHw", "mLemma", "mVariant", "mInflected", "mHwTr", "mHwTrLang", 
        "mEx", "mExTr", "mExTrLang", "mNote", "mGloss", "mUsg", "mXr",
        "transformedEntry"]
    def __init__(self, entry, m, parser, mapper, nestedEntriesWillBePromoted):
        self.entry = entry; self.m = m; self.parser = parser; self.mapper = mapper
        self.nestedEntriesWillBePromoted = nestedEntriesWillBePromoted
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
        logging.warning("Warning: no language found for %s" % elt)    
        return None
    def FindLanguageAll(self, hDest, hLang):
        for trDest in hDest.values(): trDest.trLanguage = self.FindLanguage(trDest, hLang)
    def FindSuitableParent(self, elt):
        # Goes up the ancestors of 'elt' until it finds one that can become its parent.
        # Returns this ancestor, plus the next one on the path from that ancestor to 'elt'.
        #s_ = etree.tostring(elt).decode("utf8"); 
        """
        s_ = EltToStr(elt)
        print(s_[:150])
        t_ = "als er geen toezicht is"
        if t_ in s_: # 
            i = s_.find(t_)
            print("### <%s> %s" % (elt.tag, repr(s_[max(0, i - 40):(i + 40)])))
            i = i
        if "entryPlaceholder" in elt.tag:
            i = -1
        """
        eltTag = elt.tag; allowedParents = allowedParentHash[eltTag]
        cur = elt; parent = cur.getparent()
        # If nested entries will be promoted to the top level anyway, we don't need to check
        # whether the placeholders have a suitable parent, because the nested entry won't stay where
        # the placeholder is now.
        if eltTag == ELT_ENTRY_PLACEHOLDER and self.nestedEntriesWillBePromoted: return (parent, cur)
        #print("FindSuitableParent for %s" % elt)
        while not (parent is None):
            parentTag = parent.tag
            #print("- Considering %s, allowed = %s" % (parent.tag, allowedParents))
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
        # This method returns None if processing should continue with elt's children;
        # otherwise it returns the node where processing should continue (this will be a segified
        # copy of 'elt' in cases when the original 'elt' has been moved to become a sibling of
        # one of its former ancestors; this means we'll encounter it again later, though we won't
        # have to move it then).
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
                return segifiedSubtree
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
                next = self.StageTwo_TransformSubtree(cur)
                if next is not None: prev = None; cur = next
            # If we entered from the parent, we'll move into the first child,
            # otherwise into the child following 'prev'.
            i = -1 if prev is None else cur.index(prev)
            if len(cur) > i + 1: prev = None; cur = cur[i + 1] # Move into the next child.
            else: prev = cur; cur = cur.getparent() # Move back into the parent.
    def StageOne_GatherIdsInSubtree(self, elt):
        h = {}
        def Rec(e):
            if type(e) is not TMyElement: return
            h[id(e)] = e
            for i in range(len(e)): Rec(e[i])
        if elt is not None: Rec(elt)
        return h
    def StageOne_TransformSubtree(self, elt, isEntry, idsInEntrySubtree):
        if type(elt) is not TMyElement: return (copy.deepcopy(elt), None)
        class TOrder:
            TYPE_SIB = 1; TYPE_MILESTONES = 2; TYPE_CONSUME = 3
            # Note that the newElt of this order might not be what is called 'newElt' 
            # within the caller's context; it could be one of the newSibs, or a decendant 
            # created using milestones.  The newElt of this order is where typeAttr should
            # be applied, as well as trOrder.trLanguage.
            __slots__ = ["newTag", "trOrder", "typeAttr", "type", "newElt", "addOrigValueAsAttr", "addMappedValueAsAttr"]
            def __init__(self, newTag, trOrder, typeAttr = "", addOrigValueAsAttr = [], addMappedValueAsAttr = []):
                self.newTag = newTag; self.trOrder = trOrder; self.typeAttr = typeAttr
                self.addOrigValueAsAttr = addOrigValueAsAttr[:]
                self.addMappedValueAsAttr = addMappedValueAsAttr[:]
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
        if eltId in self.mPos: orders.append(TOrder(ELT_gram, self.mPos[eltId], typeAttr = "pos", addOrigValueAsAttr=[ATTR_orig_UNPREFIXED], addMappedValueAsAttr=[ATTR_META_POS_FOR_ID]))
        if eltId in self.mHw: orders.append(TOrder(ELT_orth, self.mHw[eltId], typeAttr = "lemma", addMappedValueAsAttr=[ATTR_META_HEADWORD_FOR_ID]))
        if eltId in self.mInflected: orders.append(TOrder(ELT_orth, self.mInflected[eltId], typeAttr = "inflected"))
        if eltId in self.mVariant: orders.append(TOrder(ELT_orth, self.mVariant[eltId], typeAttr = "variant"))
        if eltId in self.mLemma: orders.append(TOrder(ELT_orth, self.mLemma[eltId], typeAttr = "simple"))
        if eltId in self.mHwTr: orders.append(TOrder(ELT_cit, self.mHwTr[eltId], typeAttr = "translationEquivalent"))
        if eltId in self.mEx: orders.append(TOrder(ELT_cit, self.mEx[eltId], typeAttr = "example"))
        if eltId in self.mExTr: orders.append(TOrder(ELT_cit, self.mExTr[eltId], typeAttr = "translation"))
        if eltId in self.mNote: orders.append(TOrder(ELT_note, self.mNote[eltId]))
        if eltId in self.mGloss: orders.append(TOrder(ELT_gloss, self.mGloss[eltId]))
        if eltId in self.mUsg: orders.append(TOrder(ELT_usg, self.mUsg[eltId], typeAttr = "hint"))
        if eltId in self.mXr: orders.append(TOrder(ELT_xr, self.mXr[eltId], typeAttr = "related"))
        # If the current element is the future <entry>, also process any orders that refer to nodes outside the entry.
        # These can't be transformed (since they're outside), so they will have to result in siblings.
        if isEntry:
            def _(trOrderHash, newTag, typeAttr_):
                for eltId, trOrder in trOrderHash.items():
                    if eltId in idsInEntrySubtree: continue
                    order = TOrder(newTag, trOrder, typeAttr = typeAttr_)
                    order.type = TOrder.TYPE_SIB
                    orders.append(order)
            _(self.mDef, ELT_def, "")
            _(self.mPos, ELT_gram, "pos")
            _(self.mHw, ELT_orth, "lemma")
            _(self.mLemma, ELT_orth, "simple")
            _(self.mVariant, ELT_orth, "variant")
            _(self.mInflected, ELT_orth, "inflected")
            _(self.mHwTr, ELT_cit, "translationEquivalent")
            _(self.mEx, ELT_cit, "example")
            _(self.mExTr, ELT_cit, "translation")
            _(self.mNote, ELT_note, "")
            _(self.mGloss, ELT_gloss, "")
            _(self.mUsg, ELT_usg, "hint")
            _(self.mXr, ELT_xr, "related")
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
            (newChild, newChildSibs) = self.StageOne_TransformSubtree(elt[i], False, None)
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
            for attrName in o.addOrigValueAsAttr: o.newElt.set(attrName, o.trOrder.matchedStr)
            for attrName in o.addMappedValueAsAttr: o.newElt.set(attrName, o.trOrder.finalStr)
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
        elif eltId in self.mInflected: newTag = ELT_orth; trOrder = self.mInflected[eltId]; typeAttr = "inflected"
        elif eltId in self.mVariant: newTag = ELT_orth; trOrder = self.mVariant[eltId]; typeAttr = "variant"
        elif eltId in self.mHwTr: newTag = ELT_cit; trOrder = self.mHwTr[eltId]; typeAttr = "translationEquivalent"
        elif eltId in self.mEx: newTag = ELT_cit; trOrder = self.mEx[eltId]; typeAttr = "example"
        elif eltId in self.mExTr: newTag = ELT_cit; trOrder = self.mExTr[eltId]; typeAttr = "translation"
        elif eltId in self.mNote: newTag = ELT_note; trOrder = self.mNote[eltId]
        elif eltId in self.mGloss: newTag = ELT_gloss; trOrder = self.mGloss[eltId]
        elif eltId in self.mUsg: newTag = ELT_usg; trOrder = self.mUsg[eltId]; typeAttr = "hint"
        elif eltId in self.mXr: newTag = ELT_xr; trOrder = self.mXr[eltId]; typeAttr = "related"
        elif elt.tag == ELT_ENTRY_PLACEHOLDER: newTag = elt.tag
        else: newTag = ELT_seg
        needsMilestones = False; newSib = None
        if trOrder != None and trOrder.finalStr != trOrder.matchedStr:
            logging.info("# %s -> %s" % (trOrder.matchedStr, trOrder.finalStr))
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
        idsInEntrySubtree = self.StageOne_GatherIdsInSubtree(self.entry)
        (newEntry, newSibs) = self.StageOne_TransformSubtree(self.entry, True, idsInEntrySubtree)
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
        elif elt.tag == ELT_usg or elt.tag == ELT_xr:
            ty = elt.get(ATTR_TEMP_type, None)
            if ty is not None: 
                elt.set(ATTR_type_UNPREFIXED, ty)
                elt.attrib.pop(ATTR_TEMP_type, None)
            # An <xr> may not contain character data directly, so it should be wrapped into <seg>s.
            # - Update: now we want to use <ref>s instead of <seg>s.
            if elt.tag == ELT_xr:
                children = [child for child in elt]
                if elt.text and not elt.text.isspace():
                    sib = self.mapper.Element(ELT_ref); sib.text = elt.text; elt.text = ""
                    sib.set(ATTR_type_UNPREFIXED, "reference")
                    if children: children[0].addprevious(sib)
                    else: elt.append(sib)
                for child in children:
                    if child.tag == ELT_seg: child.tag = ELT_ref
                    if not (child.tail and not child.tail.isspace()): continue
                    sib = self.mapper.Element(ELT_ref); sib.text = child.tail; child.tail = ""
                    child.addnext(sib)
        elif elt.tag == ELT_entry:
            # An entry may not contain <seg>s, so they should be changed into <dictScraps>.
            # It may also not contain character data and <def>s, so we'll wrap those things into <dictScraps>.
            # - Update: they changed the spec so that <dictScrap> can no longer contain a <def>,
            # so we'll wrap <def>s into <sense>s instead.
            if IsNonSp(elt.text):
                child = self.mapper.Element(ELT_dictScrap); child.text = elt.text
                elt.insert(0, child)
            elt.text = None
            child = GetFirstChild(elt)
            while child is not None:
                if IsNonSp(child.tail): 
                    sib = self.mapper.Element(ELT_dictScrap); sib.text = child.tail
                    elt.addnext(sib)
                child.tail = None; nextChild = child.getnext()
                if child.tag == ELT_seg: 
                    child.tag = ELT_dictScrap
                elif child.tag == ELT_def:
                    newChild = self.mapper.Element(ELT_sense)
                    elt.replace(child, newChild)
                    newChild.append(child)
                child = nextChild
    # This function adds, to each <sense> and <entry> element, two attributes from the meta namespace
    # giving the first headword and the first part-of-speech value from that sense/entry.
    # This will be used later to generate IDs.
    def StageThree_PrepareForIds(self, root):
        class TSenseRec:
            __slots__ = ["elt", "pos", "headword"]
            def __init__(self, elt): self.elt = elt; self.pos = None; self.headword = None
            def SetAttrib(self, entry):
                self.elt.set(ATTR_META_HEADWORD_FOR_ID, self.headword or entry.headword or "")
                self.elt.set(ATTR_META_POS_FOR_ID, self.pos or entry.pos or "")
        entryRec = TSenseRec(root)
        senseRecs = [entryRec]
        def Rec(elt, curSenseRec):
            if elt.tag == ELT_sense:
                curSenseRec = TSenseRec(elt); senseRecs.append(curSenseRec)
            hw = elt.attrib.pop(ATTR_META_HEADWORD_FOR_ID, None)
            if hw: 
                if not entryRec.headword: entryRec.headword = hw
                if curSenseRec and not curSenseRec.headword: curSenseRec.headword = hw
            pos = elt.attrib.pop(ATTR_META_POS_FOR_ID, None)
            if pos:
                if not entryRec.pos: entryRec.pos = pos
                if curSenseRec and not curSenseRec.pos: curSenseRec.pos = hw
            for child in elt: Rec(child, curSenseRec)
        Rec(root, entryRec)
        for rec in senseRecs: rec.SetAttrib(entryRec)
    def StageThree(self):
        self.StageThree_ProcessSubtree(self.transformedEntry)
        self.StageThree_PrepareForIds(self.transformedEntry)
    def TransformEntry(self): 
        self.senseIds = set(id(x) for x in ([] if not self.m.selSense else self.m.selSense.findall(self.entry)))
        #mSense = self.MakeTrOrderHashFromSelector(self.m.selSense)
        self.mDef = self.MakeTrOrderHash(self.m.xfDef, MATCH_def)
        self.mPos = self.MakeTrOrderHash(self.m.xfPos, MATCH_pos)
        self.mHw = self.MakeTrOrderHash(self.m.xfHw, MATCH_hw)
        self.mVariant = self.MakeTrOrderHash(self.m.xfVariant, MATCH_variant)
        self.mInflected = self.MakeTrOrderHash(self.m.xfInflected, MATCH_inflected)
        self.mLemma = self.MakeTrOrderHash(self.m.xfLemma, MATCH_lemma)
        self.mHwTrLang = self.MakeTrOrderHash(self.m.xfHwTrLang, MATCH_hw_tr_lang)
        self.mHwTr = self.MakeTrOrderHash(self.m.xfHwTr, MATCH_hw_tr)
        self.mEx = self.MakeTrOrderHash(self.m.xfEx, MATCH_ex)
        self.mExTrLang = self.MakeTrOrderHash(self.m.xfExTrLang, MATCH_ex_tr_lang)
        self.mExTr = self.MakeTrOrderHash(self.m.xfExTr, MATCH_ex_tr)
        self.mGloss = self.MakeTrOrderHash(self.m.xfGloss, MATCH_gloss)
        self.mNote = self.MakeTrOrderHash(self.m.xfNote, MATCH_note)
        self.mUsg = self.MakeTrOrderHash(self.m.xfUsg, MATCH_usg)
        self.mXr = self.MakeTrOrderHash(self.m.xfXr, MATCH_xr)
        self.FindLanguageAll(self.mHwTr, self.mHwTrLang)
        self.FindLanguageAll(self.mExTr, self.mExTrLang)
        if Verbose: logging.info("TEntryMapper: %d sense elements, %d headwords, %d lemmas, %d variants, %d infected forms, %s definitions, %d part-of-speech, %d translations (%d lang), %d examples, %d translated examples (%d lang), %d glosses, %d notes, %d usgs, %d xrs." % (
            len(self.senseIds), len(self.mHw), len(self.mLemma), len(self.mVariant), len(self.mInflected), len(self.mDef), len(self.mPos), len(self.mHwTr), len(self.mHwTrLang),
            len(self.mEx), len(self.mExTr), len(self.mExTrLang), len(self.mGloss), len(self.mNote), len(self.mUsg), len(self.mXr)))
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
        if Verbose: logging.info("After stage one:\n%s" % etree.tostring(self.transformedEntry, pretty_print = True).decode("utf8"))
        # Move things around when needed to set up proper parent/child relationships.
        self.StageTwo()
        assert self.transformedEntry.tag == ELT_entry
        if Verbose: logging.info("After stage two:\n%s" % etree.tostring(self.transformedEntry, pretty_print = True).decode("utf8"))
        # Stage 3: expand orth into form/orth, gram into gramGrp/gram, and cit into cit/quote;
        # and if the root <entry> has any children of the wrong type, wrap them into <dictScrap>s.
        self.StageThree()
        if Verbose: logging.info("After stage three:\n%s" % etree.tostring(self.transformedEntry, pretty_print = True).decode("utf8"))
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

class TTransformEntryTask:
    __slots__ = ["curLeft", "curRight", "inEntry", "outEntry", "fut", "placeholder", "xmlLangAttribute", "inEntryStr", "outEntryStr"]
    def __init__(self, curLeft, curRight, inEntry): self.curLeft = curLeft; self.curRight = curRight; self.inEntry = inEntry
def CallTransformEntry(inEntryStr, mapping, nestedEntriesWillBePromoted, xmlLangAttribute): 
    #sys.stdout.write("CallTransformEntry %d begins\n" % len(inEntryStr)); sys.stdout.flush()
    parserLookup = etree.ElementDefaultClassLookup(element = TMyElement)
    parser = etree.XMLParser()
    parser.set_element_class_lookup(parserLookup)
    f = io.StringIO(inEntryStr.decode("utf8"))
    tree = etree.ElementTree(file = f, parser = parser)
    f.close()
    inEntry = tree.getroot()
    inEntry.xmlLangAttribute = xmlLangAttribute
    treeMapper = TTreeMapper(tree, mapping, parser, None, False, nestedEntriesWillBePromoted)
    treeMapper.FindEntries(inEntry) # fills treeMapper.entryHash and treeMapper.eltHash; but it might fail to find the entry because the xpath expression assumed that the entry is still a part of the original XML document; no matter, the important thing is to fill eltHash to keep the elements alive
    treeMapper.entryHash = { id(inEntry) : inEntry }
    entryMapper = TEntryMapper(inEntry, treeMapper.m, treeMapper.parser, treeMapper, treeMapper.nestedEntriesWillBePromoted)
    transformedEntry = entryMapper.TransformEntry()
    outEntryStr = etree.tostring(transformedEntry, pretty_print = False, encoding = "utf8").decode("utf8")
    #sys.stdout.write("CallTransformEntry %d ends %d\n" % (len(inEntryStr), len(outEntryStr))); sys.stdout.flush()
    return outEntryStr
def CallTransformEntry_Multi(mapping, nestedEntriesWillBePromoted, params):
    results = []
    for (inEntryStr, xmlLangAttribute) in params:
        outEntryStr = CallTransformEntry(inEntryStr, mapping, nestedEntriesWillBePromoted, xmlLangAttribute)
        results.append(outEntryStr)
    return results

class TDummyFuture:
    __slots__ = ["value"]
    def __init__(self, value): self.value = value
    def result(self): return self.value
    def wait(self): pass
class TDummyExecutor:
    def __init__(self): pass
    def submit(self, func, *args, **kwargs):
        result = func(*args, **kwargs)
        return TDummyFuture(result)
    def shutdown(self, wait): pass

class TPlaceholderRec:
    __slots__ = ["placeholderElt", "origEntry", "transformedEntry", "pid"]
    def __init__(self, pid): self.pid = pid

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
        "nestedEntriesWillBePromoted", # will nested entries eventually be promoted to the top level?
        ]
    def __init__(self, tree, m, parser, relaxNg, makeAugTree, nestedEntriesWillBePromoted): # m = mapping
        self.tree = tree
        self.m = m
        self.parser = parser
        self.keepAliveHash = {}
        self.relaxNg = relaxNg
        self.augTree = None
        self.nestedEntriesWillBePromoted = nestedEntriesWillBePromoted
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
        if type(e) is CommentType:
            ae = etree.Comment(e.text)
            ae.tail = e.tail
            self.keepAliveHash[id(e)] = e
            self.keepAliveHash[id(ae)] = ae
            # e.augNode = ae
            augmentedNodes.add(id(e))
            return ae
        ae = self.parser.makeelement(e.tag, e.attrib, nsmap)
        self.keepAliveHash[id(e)] = e
        self.keepAliveHash[id(ae)] = ae
        ae.text = e.text; ae.tail = e.tail
        p = etree.XMLParser()
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
        counter = 0; tmStart = time.perf_counter(); tmPrev = tmStart; counterPrev = counter
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
                tmNow = time.perf_counter()
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
    #@profile  # https://gist.github.com/danriti/8015889
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
            parent = cur.getparent(); 
            # iCur = parent.index(cur);   # Element::index seems to be O(return value)
            # assert iCur >= 0
            #print("Going up the left branch.  parent = %s" % id(parent))
            if parent.IsAncestorOf(entryR): 
                lca = parent; # lcaLeftBranch = iCur; 
                lcaLeftBranchElt = cur
                break
            #nChildren = len(parent)
            #print("cur = %s, parent = %s, iCur = %d" % (cur, parent, iCur))
            segParent = self.SegifyElt(parent)
            segParent.text = entryL.tail if cur is entryL else ""
            leftTailToDo = None # was consumed
            if IsNonSp(segParent.text) or IsNonSp(segParent.tail): anythingScrappedL = True
            if segCur is not None: segParent.append(segCur)
            sib = cur
            while True:
                sib = sib.getnext()
                if sib is None: break
                segSib = self.SegifySubtree(sib)
                segParent.append(segSib)
                anythingScrappedL = True
            """
            if iCur < nChildren - 1:
                for iSib in range(iCur + 1, nChildren):
                    segSib = self.SegifySubtree(parent[iSib])
                    segParent.append(segSib)
                    anythingScrappedL = True
            """
            cur = parent; segCur = segParent
        segL = segCur
        #
        anythingScrappedR = False; segCur = None; cur = entryR
        while True:
            parent = cur.getparent()
            #print("Going up the right branch.  parent = %s, lca = %s" % (id(parent), id(lca)))
            # iCur = parent.index(cur); # slow
            # assert iCur >= 0
            if parent is lca: 
                #lcaRightBranch = iCur; 
                lcaRightBranchElt = cur; 
                break
            segParent = self.SegifyElt(parent)
            segParent.tail = ""
            if IsNonSp(segParent.text): anythingScrappedR = True
            for sib in parent:
                if sib is cur: break
                segSib = self.SegifySubtree(sib)
                segParent.append(segSib)
                anythingScrapped = True
            """
            if iCur > 0:
                for iSib in range(iCur):
                    segSib = self.SegifySubtree(parent[iSib])
                    segParent.append(segSib)
                    anythingScrapped = True
            """
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
        # - Holy shit: Element::__len__ seems to be O(nChildren).  https://github.com/lxml/lxml/blob/master/src/lxml/etree.pyx  and _countElements in https://github.com/lxml/lxml/blob/master/src/lxml/apihelpers.pxi
        #nChildren = len(lca)
        #print("lca has %d children, left = %d, right = %d" % (nChildren, lcaLeftBranch, lcaRightBranch))
        # assert 0 <= lcaLeftBranch < lcaRightBranch < nChildren
        if segL is not None: lcaL.append(segL)
        #if lcaRightBranch - lcaLeftBranch > 1 or leftTailToDo:
        if lcaLeftBranchElt.getnext() is not lcaRightBranchElt or leftTailToDo:
            if anythingScrappedR and not anythingScrappedL: dest = lcaR; anythingScrappedR = True
            else: dest = lcaL; anythingScrappedL = True
            if leftTailToDo: dest.text = leftTailToDo; leftTailToDo = None
            elt = lcaLeftBranchElt
            while True:
                elt = elt.getnext()
                if elt is lcaRightBranchElt: break
                dest.append(self.SegifySubtree(elt))
            """
            for iChild in range(lcaLeftBranch + 1, lcaRightBranch):
                dest.append(self.SegifySubtree(lca[iChild]))
            """
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
        # - Update: we no longer assume that it's detached from the tree.
        ###assert entry.getparent() is None
        SetMatchInfo(entry, MATCH_entry)
        entryMapper = TEntryMapper(entry, self.m, self.parser, self, self.nestedEntriesWillBePromoted)
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
        # - Do not detach the entry from the rest of the tree; some selectors may refer to things outside the entry.
        doDetach = True
        if doDetach and parent is not None: parent[idx] = placeholder; assert entry.getparent() is None
        placeholder.transformedEntry = self.TransformDetachedEntry(entry)
        if not doDetach and parent is not None: parent[idx] = placeholder
        return placeholder
    def TransformEntryWithFuture(self, task, executor):
        # Like 'TransformEntry', but with concurrency.  This function submits a call to
        # CallTransformEntry to 'executor' and stores the resulting future into 'task.fut'.
        # 'executor' may be None, in which case this function will just prepare, in 'task',
        # the parameters needed for CallTransformEntry (i.e. 'inEntryStr' and 'xmlLangAttribute').
        entry = task.inEntry
        # Replace 'entry' in its current tree with a placeholder element,
        # whose 'transformedEntry' member will point to the transformed version of 'entry'.
        # This is intended to be used for non-nested entries, so the placeholder
        # is not added to 'self.placeholders'.
        parent = entry.getparent()
        #if parent is not None: idx = parent.index(entry); assert idx >= 0  # Element::index() is O(return value), we'll use .replace below to avoid having to know the index
        task.placeholder = self.Element(ELT_ENTRY_PLACEHOLDER)
        #if addToPlaceholders: self.entryPlaceholders.append(placeholder)
        # - This version has to detach the entry.
        #if parent is not None: parent[idx] = task.placeholder; assert entry.getparent() is None
        if parent is not None: parent.replace(entry, task.placeholder); assert entry.getparent() is None
        SetMatchInfo(entry, MATCH_entry)
        newParser = etree.XMLParser()
        newParser.set_element_class_lookup(etree.ElementDefaultClassLookup(element = TMyElement))
        inEntryStr = etree.tostring(task.inEntry, pretty_print = False, encoding = "utf8")
        xmlLangAttribute = getattr(entry, "xmlLangAttribute", None)
        #CallTransformEntry(inEntryStr, self.m, self.nestedEntriesWillBePromoted, xmlLangAttribute)
        if executor is None: task.xmlLangAttribute = xmlLangAttribute; task.inEntryStr = inEntryStr
        else: task.fut = executor.submit(CallTransformEntry, inEntryStr, self.m, self.nestedEntriesWillBePromoted, xmlLangAttribute)
    def TransformNonTopEntries(self):
        # We'll process the non-top entries in increasing order of exitTime.
        # This ensures that subentries are processed before their parent entries.
        L = [(entry.exitTime, entry) for entry in self.entryHash.values() if not (entry.outermostContainingEntry is None)]
        assert len(L) == len(self.entryHash) - len(self.topEntryList)
        L.sort()
        self.entryPlaceholders = []; nDone = 0
        for dummy, entry in L: 
            nDone += 1
            parent = entry.getparent(); assert not (parent is None)
            #idx = parent.index(entry); assert idx >= 0
            placeholder = self.Element(ELT_ENTRY_PLACEHOLDER)
            pr = TPlaceholderRec(len(self.entryPlaceholders)); self.entryPlaceholders.append(pr)
            pr.placeholderElt = placeholder; pr.origEntry = entry
            pidStr = str(pr.pid); placeholder.set(ATTR_PLACEHOLDER_ID, pidStr); entry.set(ATTR_PLACEHOLDER_ID, pidStr)
            # - Do not detach the entry from the rest of the tree; some selectors may refer to things outside the entry.
            ###parent[idx] = placeholder; assert entry.getparent() is None
            if len(L) < 20 or nDone % 1000 == 0: logging.info("[%d/%d] Transforming detached entry %d %s" % (nDone, len(L), id(entry), entry))
            pr.transformedEntry = self.TransformDetachedEntry(entry)
            #parent[idx] = placeholder
            parent.replace(entry, placeholder)
            #print("Transformed entry: %s %d" % (placeholder.transformedEntry, len(placeholder.transformedEntry)))
    def ReplacePlaceholders(self, root):  # for non-top entries
        #for placeholder in self.entryPlaceholders:
        Verbose = False
        def Rec(elt):
            #for i in range(len(elt)): Rec(elt[i])  # Element::__getitem__(int) is expensive
            for child in elt: Rec(child)
            if elt.tag == ELT_ENTRY_PLACEHOLDER:
                pid = int(elt.get(ATTR_PLACEHOLDER_ID))
                pr = self.entryPlaceholders[pid]
                placeholder = pr.placeholderElt; transformedEntry = pr.transformedEntry
                if Verbose: logging.info("Placeholder = %s [len %d] %s" % (placeholder, len(placeholder), transformedEntry))
                #if len(placeholder) > 0: print("- Its child: %s" % repr(placeholder[0][0].tail))
                #assert len(placeholder) == 0
                parent = elt.getparent()
                #idx = parent.index(elt); assert idx >= 0  # Element::index is expensive
                assert transformedEntry is not None
                if Verbose: logging.info("Transformed entry: %d %s" % (transformedEntry.entryTime, transformedEntry))
                if Verbose: logging.info("Its parent: %s" % transformedEntry.getparent())
                assert transformedEntry.getparent() is None
                #parent[idx] = transformedEntry  # expensive, use replace instead
                parent.replace(elt, transformedEntry)
                assert elt.getparent() is None
                assert transformedEntry.getparent() is parent
        Rec(root)
    def BuildBody(self):
        # Builds a <body> element with the list of all top (i.e. non-nested) entries
        # (actually placeholders of transformed top entries).  Anything in between entries
        # in the original tree gets scrapified and included in the transformed entries.
        # Entries are processed in batches, each batch being submitted to an executor
        # from 'concurrent.futures'.
        outBody = self.Element(ELT_body); self.outBody = outBody
        nTopEntries = len(self.topEntryList)
        import concurrent.futures
        nProcesses = 20
        # Experiments on lozjpctpsbpxqomuzuwy-LEX-ML_OUT.xml , batches of 10000 entries:
        # - TDummyExecutor (i.e. no concurrency): 1000 entries/sec  [calling plain old TransformEntry should be even better as it would save us the trouble of converting the entry to a string before and after the transformation]
        # - ThreadPoolExecutor(20 threads): 800 entries/sec
        # - ProcessPoolExecutor(20 processes): 3300-3700 entries/sec
        if nTopEntries >= 100: # avoid the overheads of creating subprocesses for very small input documents
            executor = concurrent.futures.ProcessPoolExecutor(nProcesses)
        else:
            executor = TDummyExecutor()
        #executor = concurrent.futures.ThreadPoolExecutor(nProcesses)
        #executor = TDummyExecutor()
        #print("\n\n###### BuildBody")
        if nTopEntries == 0:
            logging.warning("Warning: no entries found.")
            outBody.append(self.SegifySubtree(self.tree.getroot()))
        else:
            nextLeft = self.ScrapifyLeft(self.topEntryList[0])
            tmStart = time.perf_counter(); iPrev = 0; tmPrev = tmStart
            batchSize = 10000; nBatches = (nTopEntries + batchSize - 1) // batchSize
            for batchNo in range(nBatches):
                batchFrom = batchNo * batchSize; batchTo = min(batchFrom + batchSize, nTopEntries)
                Verbose3 = False
                def Tm(): return float(time.perf_counter() - tmPrev)
                if True or Verbose2: #  and i % 1000 == 0: 
                    tmNow = time.perf_counter()
                    sys.stdout.write("BuildBody transforming entry %d/%d  (%.2f sec; %.2f entries/sec, recently %.2f)     \r" % (batchFrom, nTopEntries,
                        tmNow - tmStart, batchFrom / max(0.1, tmNow - tmStart), (batchFrom - iPrev) / max(0.1, tmNow - tmPrev))); sys.stdout.flush()
                    tmPrev = time.perf_counter(); iPrev = batchFrom
                    #if batchNo >= 20: sys.exit(0)
                if Verbose3: sys.stdout.write("Batch %d, preparing tasks\n" % batchNo); sys.stdout.flush()
                # Prepare a TTransformEntryTask structure for each entry in this batch.
                # Also scrapify anything between these entries.
                tasks = []; tasksByProcess = [[] for j in range(nProcesses)]; tm1 = 0; tmS = 0
                for i in range(batchFrom, batchTo):
                    curLeft = nextLeft
                    tmS -= Tm()
                    if i == nTopEntries - 1:
                        curRight = self.ScrapifyRight(self.topEntryList[i])
                    else:
                        nextLeft, curRight = self.ScrapifyBetween(self.topEntryList[i], self.topEntryList[i + 1])
                    tmS += Tm()
                    inEntry = self.topEntryList[i]
                    inEntry.tail = None # if there was a tail, it was already included in the curRight scrap
                    # outEntry = self.TransformEntry(inEntry).transformedEntry
                    task = TTransformEntryTask(curLeft, curRight, inEntry)
                    tm1 -= Tm()
                    self.TransformEntryWithFuture(task, None)
                    tm1 += Tm()
                    tasks.append(task)
                    tasksByProcess[i % nProcesses].append(task)
                if Verbose3: sys.stdout.write("[%.2f; %.2f in TransformEntryWithFuture; %2.f scrapifying] Batch %d, calling subprocesses\n" % (Tm(), tm1, tmS, batchNo)); sys.stdout.flush()
                # Send the tasks to the executor.  We'll have one "sub-batch" for each process in the pool.
                futs = []
                for j in range(nProcesses):
                    params = [(task.inEntryStr, task.xmlLangAttribute) for task in tasksByProcess[j]]
                    fut = executor.submit(CallTransformEntry_Multi, self.m, self.nestedEntriesWillBePromoted, params)
                    futs.append(fut)
                if Verbose3: sys.stdout.write("[%.2f] Batch %d, gathering results\n" % (Tm(), batchNo)); sys.stdout.flush()
                # Gather the results, i.e. wait for the processes to finish processing their sub-batches.
                for j in range(nProcesses):
                    results = futs[j].result()
                    assert len(results) == len(tasksByProcess[j])
                    for i, task in enumerate(tasksByProcess[j]):
                        task.outEntryStr = results[i]
                if Verbose3: sys.stdout.write("[%.2f] Batch %d, processing results\n" % (Tm(), batchNo)); sys.stdout.flush()
                # Process the results.
                for task in tasks:
                    curLeft = task.curLeft; curRight = task.curRight
                    # Parse the transformed entry string into an element tree.
                    #outEntryStr = task.fut.result(); 
                    outEntryStr = task.outEntryStr
                    f = io.StringIO(outEntryStr)
                    outEntryTree = etree.ElementTree(file = f, parser = self.parser)
                    f.close()
                    outEntry = outEntryTree.getroot()
                    task.outEntry = outEntry
                    # Attach the transformed entry to the placeholder element.
                    task.outEntry.originalElement = task.inEntry   # actually we no longer use 'originalElement' for anything
                    task.placeholder.transformedEntry = outEntry
                    #print("i = %d, curLeft = %s, curRight = %s" % (i, curLeft, curRight))
                    # Insert the scrapified versions of any other elements between the entries.
                    if curLeft is not None: 
                        assert not curLeft.tail
                        curLeft.tail = outEntry.text; outEntry.text = None
                        if curLeft.tag == ELT_seg: curLeft.tag = ELT_dictScrap
                        outEntry.insert(0, curLeft)
                        #print("outEntry = now %s" % outEntry)
                    if curRight is not None: 
                        if curRight.tag == ELT_seg: curRight.tag = ELT_dictScrap
                        outEntry.append(curRight)
                    #for key, val in task.treeMapper.keepAliveHash.items(): self.keepAliveHash[key] = val
                    outBody.append(outEntry)
                if Verbose3: sys.stdout.write("[%.2f] Batch %d, done\n" % (Tm(), batchNo)); sys.stdout.flush()
        executor.shutdown(True)
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
        if verbose: logging.info("Transform")
        oldRoot = self.tree.getroot()
        newRoot = self.InsertTempRoot(oldRoot)
        self.FindEntries(newRoot) # fills self.entryHash and self.eltHash
        if verbose: logging.info("FindEntries found %d entries, %d elements." % (len(self.entryHash), len(self.eltHash)))
        self.MarkEntries() # fills self.topEntryList
        if verbose: logging.info("MarkEntries found %d top-levelentries." % (len(self.topEntryList)))
        self.SetEntryLangs(newRoot) # sets the 'xmlLangAttribute' attribute of the entry Element objects
        if verbose: logging.info("SetEntryLangs returned.")
        self.RemoveTempRoot(newRoot)
        if verbose: logging.info("RemoveTempRoot returned.")
        self.TransformNonTopEntries()
        if verbose: logging.info("TransformNonTopEntries returned.")
        self.BuildBody()  
        if verbose: logging.info("BuildBody returned.")
        self.ReplacePlaceholders(self.outBody)  # replace placeholders with transformed entries
        if verbose: logging.info("ReplacePlaceholders returned.")
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
        # https://raw.githubusercontent.com/DARIAH-ERIC/lexicalresources/master/Schemas/TEILex0/out/TEILex0.rng
        with open("app/modules/transformator/TEILex0-ODD.rng", "rt", encoding = "utf8") as f:
            relaxNgDoc = etree.parse(f)
        self.relaxNg = etree.RelaxNG(relaxNgDoc)
    def E(self, tag, attrib_ = {}, children = [], text = None, tail = None):
        e = self.parser.makeelement(tag, attrib = attrib_, nsmap = NS_MAP)
        # This can be very slow if the tree is large; see _appendChild in https://github.com/lxml/lxml/blob/master/src/lxml/apihelpers.pxi
        # and moveNodeToDocument in https://github.com/lxml/lxml/blob/master/src/lxml/proxy.pxi .
        for child in children: e.append(child)
        e.text = text; e.tail = tail
        return e
    def TransformTree(self, mapping, tree, outBody, outAugTrees, nestedEntriesWillBePromoted):
        # Transforms 'tree' using a temporary instance of TTreeMapper and
        # moves the entries from its body into 'outBody'.
        makeAugTrees = outAugTrees is not None
        treeMapper = TTreeMapper(tree, mapping, self.parser, self.relaxNg, makeAugTrees, nestedEntriesWillBePromoted)
        treeMapper.Transform()
        inBody = treeMapper.outBody; nElts = 0
        children = [child for child in inBody]
        for child in children:
            inBody.remove(child)
            outBody.append(child)
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
        """This is a somewhat more conservative version of StripDictScrap.  It removes a <seg> or
        <dictScrap> only if it has no children (and if its parent is able to contain whatever
        character data was inside the <seg> or <dictScrap>).  This rule is applied bottom-up, 
        so that several levels of nested <seg>s can still be stripped, as long as they don't contain
        any non-scrap elements."""
        def Rec(elt):
            if type(elt) is not TMyElement: return
            eltCanContainText = elt.tag in allowedParentHash[ELT_PSEUDO_text]
            childrenToRemove = []
            for child in elt:
                Rec(child)
                if IsScrap(child) and GetFirstChild(child) is None and (eltCanContainText or ((child.text or "") + " ").isspace()): childrenToRemove.append(child)
            for child in childrenToRemove: 
                RemoveElementAndPromoteChildren(child, True)
        Rec(root)        
    def StripDictScrap_Thorough(self, root, deleteTextOnlyScraps):
        """This version of StripDictScrap applies the following principle: if a <seg> or <dictScrap> has only
        such children as could also be children of its parent, then this <seg> or <dictScrap> is stripped and
        its former children now become the children of its former parent.  For example,
          <a> one <seg> two <b> three </b> four </seg> five <seg> six </seg> </a>
        might become (assuming that <b> can be a child of <a>)
          <a> one  two <b> three </b> four  five  six  </a>
        Furthermore, if deleteTextOnlyScraps is True, then any <seg> or <dictScrap> that contains only
        character data is also deleted, *along with its contents*.
        """
        def Rec(elt):
            if type(elt) is not TMyElement: return
            #isScrap = IsScrap(elt)
            childrenToRemove = []; childrenToRemoveWithContent = []
            eltMayContainText = elt.tag in allowedParentHash[ELT_PSEUDO_text]
            for child in elt:
                Rec(child)
                if not IsScrap(child): continue
                canBeDeleted = True; hasText = child.text and not child.text.isspace(); hasChildren = False
                for grandchild in child:
                    hasChildren = True
                    if not (grandchild.tag in allowedParentHash and elt.tag in allowedParentHash[grandchild.tag]): 
                        canBeDeleted = False; break
                    if grandchild.tail and not grandchild.tail.isspace(): hasText = True
                # We won't delete text-only <seg>s inside <xr> because we assume that those <seg>s have
                # been inserted only because <xr> can't contain text directly, so removing them with their 
                # content would actually remove useful content of the <xr>.
                if deleteTextOnlyScraps and not hasChildren and elt.tag != ELT_xr: childrenToRemoveWithContent.append(child); continue
                if hasText and not eltMayContainText: canBeDeleted = False
                if canBeDeleted: childrenToRemove.append(child)
            # After removing a child, it may be desirable to insert spaces around it, so that e.g.
            # <ul><li>Foo</li><li>Bar</li></ul> does not become <ul>FooBar</ul> but <ul>Foo Bar</ul>.
            # But sometimes it is undesirable, e.g. <p>Foo<b>B</b>ar</p> should become <p>FooBar</p>
            # and not <p>Foo B ar</p>.  We can't really know which elements in the input document
            # are phrase-level and which are block-level, and we can't assume that xml:space will be
            # available to clarify this either.  We'll assume that most of the time, inserting spaces
            # is the better option.
            for child in childrenToRemove: RemoveElementAndPromoteChildren(child, True)
            for child in childrenToRemoveWithContent:
                child.text = ""; RemoveElementAndPromoteChildren(child, True)
            """
            if isScrap: elt.text = ""
            def GetFirstChild(x):
                for child in x: return child
                return None
            child = GetFirstChild(elt)
            while child is not None:
                if isScrap: child.tail = ""
                Rec(child)
                nextSib = child.getnext()
                if IsScrap(child) and GetFirstChild(child) is None:
                    prevSib = child.getprevious()
                    if prevSib is None: AppendToText(elt, child.text); AppendToText(elt, child.tail) 
                    else: AppendToTail(prevSib, child.text); AppendToTail(prevSib, child.tail)
                    elt.remove(child)
                child = nextSib
            if elt.tag == ELT_seg:
                # If a <seg> has a single child that is also a <seg>, remove this child and promote its children.
                #child = GetFirstChild(elt)
                #if child is not None and type(child) is TMyElement and child.tag == ELT_seg and child.getnext() is None:
                #    RemoveElementAndPromoteChildren(child)
                # If a <seg> has a child (not necessarily the only one) that is also a <seg> and that has only one child,
                # remove the inner <seg> and promote its child.
                childrenToRemove = []
                for child in elt:
                    if type(child) is not TMyElement: continue
                    if child.tag != ELT_seg: continue
                    #grandChild = GetFirstChild(child)
                    #if grandChild.getnext() is not None: continue
                    childrenToRemove.append(child)
                for child in childrenToRemove: RemoveElementAndPromoteChildren(child)
            """
        Rec(root)        
    def FixIds(self, root, acronym):
        counters = {} # key: (containingEntryId, tag); value: counter
        def GenId(tag, containingEntryId):
            nonlocal counters
            if tag == ELT_entry: containingEntryId = ""
            # We'll generate IDs of the form tag_number, where the tag
            # is stripped of any namespace prefixes.  The number will be
            # globally unique anyway.
            i = tag.find("}")
            if i >= 0: tag = tag[i + 1:]
            i = tag.find(":")
            if i >= 0: tag = tag[i + 1:]
            tag = tag.strip()
            if not tag: tag = "elt"
            counter = counters.get((containingEntryId, tag), 0)
            while True:
                counter += 1
                cand = "%s_%s" % (tag, counter)
                if containingEntryId: cand = "%s_%s" % (containingEntryId, cand)
                if cand in idsUsed: continue
                idsUsed.add(cand)
                counters[containingEntryId, tag] = counter
                return cand
        lastSenseNumberForEntry = {}; nEntries = 0
        entryHwPairs = set(); hwCounters = {}; idsUsed = set(); otherNodesWithIds = []
        fixer = TIdFixer(False); startFixer = TIdFixer(True)
        acronym = startFixer.Fix(acronym)
        def Rec2(e, containingEntryId):
            nonlocal idsUsed, counters, nEntries, lastSenseNumberForEntry
            id_ = e.get(ATTR_ID)
            if e.tag == ELT_entry: nEntries += 1
            if e.tag == ELT_entry or e.tag == ELT_sense:
                hw = e.attrib.pop(ATTR_META_HEADWORD_FOR_ID, None) or "headword"
                pos = e.attrib.pop(ATTR_META_POS_FOR_ID, None) or "pos"
                hw = fixer.Fix(hw); pos = fixer.Fix(pos)
                if e.tag == ELT_entry: 
                    hwCounter = hwCounters.get(hw, 0) + 1; hwCounters[hw] = hwCounter
                    s = "%s_%s_%d_%s" % (acronym, hw, hwCounter, pos)
                    e.set(ATTR_ID, s); containingEntryId = s; entryHwPairs.add((s, hw)); idsUsed.add(s)
                elif e.tag == ELT_sense:
                    senseNo = lastSenseNumberForEntry.get(containingEntryId, 0) + 1
                    lastSenseNumberForEntry[containingEntryId] = senseNo
                    if (containingEntryId, hw) not in entryHwPairs: 
                        hwCounter = hwCounters.get(hw, 0) + 1; hwCounters[hw] = hwCounter
                        entryHwPairs.add((containingEntryId, hw))
                    else: hwCounter = hwCounters[hw]
                    s = "%s_%s_%d_%s_%d" % (acronym, hw, hwCounter, pos, senseNo)
                    e.set(ATTR_ID, s); idsUsed.add(s)
            elif id_: otherNodesWithIds.add((e, containingEntryId))
            for child in e: Rec2(child, containingEntryId)
        # Now make sure that every <entry> and <sense> has an ID.
        Rec2(root, "")    
        # If any other existing IDs weren't unique (due to the duplication of nodes etc.),
        # we'll fix this now.
        for e, containingEntryId in otherNodesWithIds:
            id_ = e.get(ATTR_ID)
            id_ = startFixer.Fix(id_)
            if id_ in idsUsed: id_ = GenId(e.tag, containingEntryId)
            e.set(ATTR_ID, id_); idsUsed.add(id_)
        return nEntries
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
    def PromoteNestedEntries(self, root):
        nOutermostEntries = 0; nNestedEntries = 0; insertAfter = None; nestingDepth = 0
        nodesMoved = set()
        keepAlive = []
        def RecKa(node):
            keepAlive.append(node)
            for child in node: RecKa(child)
        # We need to keep the nodes alive in order to get consistent python object IDs for the assertion check below (and also for debug output).
        RecKa(root)
        if Verbose2: logging.info("Keeping %d nodes alive." % len(keepAlive))
        def Rec(node):
            nonlocal nOutermostEntries, nNestedEntries, insertAfter, nestingDepth
            if nestingDepth == 0: assert insertAfter is None
            else: assert insertAfter is not None
            if node.tag == ELT_entry:
                nestingDepth += 1
                if nestingDepth == 1: insertAfter = node; nOutermostEntries += 1
            child = None
            def _(x): 
                s = x.tag; i = s.rfind('}')
                if i >= 0: s = s[i + 1:]
                return "%d %s" % (id(x), s)
            #print("node %s %s" % (_(node), [_(x) for x in node]))
            while True:
                # Move to the next child.
                if child is None:
                    if len(node) == 0: break # no children
                    child = node[0] # first child
                else:
                    child = child.getnext() # next sibling
                    if child is None: break # this was the last child
                # If this child is not a nested entry, process it recursively.
                if not (child.tag == ELT_entry and insertAfter is not None):
                    Rec(child); continue
                # Otherwise move it after that outermost entry.  There's no need to process
                # the child recursively as we'll reach it later anyway.
                prev = child.getprevious()
                #print("Moving node %s %s (prev: %s %s; parent: %s %s) after %s %s." % (id(child), repr(child), id(prev), repr(prev), id(node), repr(node), id(insertAfter), repr(insertAfter)))
                if Verbose2: logging.info("Moving node %s (prev: %s; parent: %s; depth %d) after %s." % (_(child), _(prev), _(node), nestingDepth, _(insertAfter)))
                if Verbose2: logging.info("Parent's children before %s" % ([_(x) for x in node],))
                if id(child) in nodesMoved: 
                    logging.critical("This node was already moved!"); 
                    assert False; sys.exit(0)
                nodesMoved.add(id(child))
                if prev is None: AppendToText(node, child.tail)
                else: AppendToTail(prev, child.tail)
                node.remove(child)
                insertAfter.addnext(child)
                child.tail = insertAfter.tail; insertAfter.tail = ""
                insertAfter = child
                nNestedEntries += 1
                if Verbose2: logging.info("Parent's children now %s" % ([_(x) for x in node],))
                # Move to the previous sibling, so that we can move from it to the next
                # # sibling at the start of the next iteration.
                child = prev
            if node.tag == ELT_entry:
                assert nestingDepth >= 1
                nestingDepth -= 1
                if nestingDepth == 0: insertAfter = None
        Rec(root)
        logging.info("PromoteNestedEntries: %d existing outermost entries; %d nested entries have been promoted." % (nOutermostEntries, nNestedEntries))
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
            returnFirstEntryOnly = False, promoteNestedEntries = False,
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
        
        The 'stripDictScrap' parameter can be set to True or 1 to strip "unnecesary"
        <dictScrap> and <seg> elements from the resulting output (set it to 2 to
        strip even more of these elements, and set it to 3 to strip even more at
        the cost of losing some character cata), and 'stripHeader' can be set to True 
        to strip the <teiHeader> element from the resulting output.
        
        The 'returnFirstEntryOnly' parameter can be set to True to return
        only the first <entry> element instead of the whole TEI XML document.

        The 'promoteNestedEntries' parameter can be set to True to move all nested
        entries out of their containing entries, thus changing the formerly nested 
        entry from a descendant to a sibling.
        """
        outBody = self.E(ELT_body)
        L = []
        if metadata is None: metadata = {}
        if headerTitle and "title" not in metadata: metadata["title"] = headerTitle
        if headerPublisher and "publisher" not in metadata: metadata["publisher"] = headerPublisher
        if headerBibl and "bibl" not in metadata: metadata["bibl"] = headerBibl
        acronym = metadata.get("acronym", "")
        if not acronym:
            acronym = MakeAcronym(metadata.get("title", ""))
            metadata["acronym"] = acronym
        if not stripHeader:
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
        #
        augTrees = [] if makeAugmentedInputTrees else None
        def ProcessFile(fn, f):
            logging.info("Processing %s." % fn)
            #tree = etree.ElementTree(file = f, parser = self.parser)
            tree = etree.parse(f, parser = self.parser)
            logging.info("Done parsing %s." % fn)
            self.TransformTree(mapping, tree, outBody, augTrees, promoteNestedEntries)
        logging.info("stripHeader = %s, stripDictScrap = %s, stripForValidation = %s, returnFirstEntryOnly = %s, promoteNestedEntries = %s" % (stripHeader,
            stripDictScrap, stripForValidation, returnFirstEntryOnly, promoteNestedEntries))
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
            self.TransformTree(mapping, tree, outBody, augTrees, promoteNestedEntries)
        if stripDictScrap: 
            logging.info("Calling StripDictScrap (%s)." % stripDictScrap)
            if 2 <= stripDictScrap <= 3: self.StripDictScrap_Thorough(outBody, stripDictScrap >= 3)
            else: self.StripDictScrap(outBody)
            logging.info("StripDictScrap returned.")
        if promoteNestedEntries: 
            logging.info("Calling PromoteNestedEntries.")
            self.PromoteNestedEntries(outBody)
            logging.info("PromoteNestedEntries returned.")
        logging.info("Calling FixIds.")
        nEntries = self.FixIds(outBody, acronym)    
        logging.info("FixIds returned (%d entries)." % nEntries)
        #            
        if returnFirstEntryOnly: 
            outTei = self.GetFirstEntry(outTei)
            x = self.E(outTei.tag, {a: outTei.attrib[a] for a in outTei.attrib}, [outTei[i] for i in range(len(outTei))])
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
            logging.info("Calling StripForValidation.")
            self.StripForValidation(outTei)
            if nEntries >= 1000:
                logging.info("Skipping Relax-NG validation due to the size of the document.")
            else:
                logging.info("Calling relaxNg.validate.")
                if not self.relaxNg.validate(outTei):
                    logging.info("Relax-NG validation failed:\n%s" % (self.relaxNg.error_log))
                else:
                    logging.info("Relag-NG validation succeeded.")
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
    #f = open("WP1\\JMcCrae\\McC_xray.xml", "rt", encoding = "utf8")
    #f = open("WP1\\INT\\example-anw.xml", "rt", encoding = "utf8")
    #f = open("Haifa\\hebrew_synonyms_sample.xml", "rt", encoding = "utf8")
    #tree = etree.ElementTree(file = f, parser = myParser)
    #f.close()
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
    with open("mapping-FromLexonomy.json", "wt", encoding = "utf8") as f: json.dump(GetFromLexonomyMapping().ToJson(), f, indent = 4)
    with open("mapping-HWN.json", "wt", encoding = "utf8") as f: json.dump(GetHwnMapping().ToJson(), f, indent = 4)
    #js = GetSldMapping().ToJson()
    #json.dump(js, f, indent = 4)
    #f.close()
    #f = open("mapping-HWN.json", "rt"); js = json.load(f); f.close(); m = TMapping(js)
    #f = open("mapping-wordnet-3.json", "rt"); js = json.load(f); f.close(); m = TMapping(js)
    f = open("FromPdf2\\mapping.json", "rt"); js = json.load(f); f.close(); m = TMapping(js)
    def LoadMapping(fn): f = open(fn, "rt"); js = json.load(f); f.close(); return TMapping(js)
    #m = TMapping(js)
    #outTei, outAug = mapper.Transform(m, ["WP1\\JSI\\SLD.zip"])
    #outTei, outAug = mapper.Transform(GetSldMapping(), ["WP1\\JSI\\SLD_macka_cat.xml"], stripForValidation = True, stripDictScrap = True)
    #outTei, outAug = mapper.Transform(GetSldMapping(), "WP1\\JSI\\SLD*.xml")
    #outTei, outAug = mapper.Transform(GetAnwMapping(), "WP1\\INT\\ANW*.xml")
    #outTei, outAug = mapper.Transform(GetAnwMapping(), "ANW_wijn_wine.xml", makeAugmentedInputTrees = True, stripForValidation = True)
    #outTei, outAug = mapper.Transform(GetAnwMapping(), "WP1\\INT\\ANW_kat_cat.xml", makeAugmentedInputTrees = False, stripForValidation = True, promoteNestedEntries = False, stripDictScrap = 3, metadata = {"title": "One two three", "acronym": "A(B)C"})
    #outTei, outAug = mapper.Transform(GetDdoMapping(), "WP1\\DSL\\DSL samples\\DDO.xml", makeAugmentedInputTrees = False, stripForValidation = True, stripDictScrap = True)
    #outTei, outAug = mapper.Transform(GetMldsMapping(), "WP1\\KD\\MLDS-FR.xml", makeAugmentedInputTrees = True, stripForValidation = True, returnFirstEntryOnly = True)
    #outTei, outAug = mapper.Transform(GetSpMapping(), "WP1\\JSI\\SP2001.xml", makeAugmentedInputTrees = True, stripForValidation = True)
    #outTei, outAug = mapper.Transform(GetMcCraeTestMapping(), "WP1\\JMcCrae\\McC_xray.xml", makeAugmentedInputTrees = True, stripForValidation = False)
    #outTei, outAug = mapper.Transform(m, "WP1\\INT\\example-anw.xml", makeAugmentedInputTrees = True, stripForValidation = False, stripDictScrap = False)
    #outTei, outAug = mapper.Transform(GetHwnMapping(), "Haifa\\hebrew_synonyms_sample.xml", makeAugmentedInputTrees = True, stripForValidation = False, stripDictScrap = False)
    #outTei, outAug = mapper.Transform(m, "wordnet-3.xml", makeAugmentedInputTrees = True, stripForValidation = False, stripDictScrap = False)
    #outTei, outAug = mapper.Transform(m, "FromPdf2\\lozjpctpsbpxqomuzuwy-LEX-ML_OUT.xml", makeAugmentedInputTrees = False, stripForValidation = True, stripDictScrap = 2)
    #outTei, outAug = mapper.Transform(LoadMapping("apr21\\anw-carole.txt"), "WP1\\INT\\ANW_kat_cat.xml", makeAugmentedInputTrees = False, stripForValidation = False, promoteNestedEntries = False, stripDictScrap = False, metadata = {"title": "One two three", "acronym": "A(B)C"})
    #outTei, outAug = mapper.Transform(LoadMapping("apr21\\spec-drae.txt"), "apr21\\example-drae.xml", makeAugmentedInputTrees = False, stripForValidation = False, promoteNestedEntries = False, stripDictScrap = False, metadata = {"title": "One two three", "acronym": "A(B)C"})
    #outTei, outAug = mapper.Transform(LoadMapping("apr21\\anw_note_spec.txt"), "apr21\\anw_note.xml", makeAugmentedInputTrees = False, stripForValidation = False, promoteNestedEntries = False, stripDictScrap = False, metadata = {"title": "One two three", "acronym": "A(B)C"})
    outTei, outAug = mapper.Transform(LoadMapping("sep21\\anw-final.txt"), "sep21\\xjjtdvtjmpjtnpmpcvnq.xml", makeAugmentedInputTrees = False, stripForValidation = False, promoteNestedEntries = False, stripDictScrap = False, metadata = {"title": "One two three", "acronym": "A(B)C"})
    #outTei, outAug = mapper.Transform(GetAnwMapping(), "jul21\\rhwcd-a02.xml", makeAugmentedInputTrees = False, stripForValidation = True, promoteNestedEntries = False, stripDictScrap = 3, metadata = {"title": "One two three", "acronym": "A(B)C"})
    f = open("transformed.xml", "wt", encoding = "utf8")
    # encoding="utf8" is important when calling etree.tostring, otherwise
    # it represents non-ascii characters in attribute names with entities,
    # which is invalid XML.
    f.write(etree.tostring(outTei, pretty_print = True, encoding = "utf8").decode("utf8"))
    f.close()
    if outAug and outAug[0] is not None:
        f = open("augmented-input.xml", "wt", encoding = "utf8")
        f.write(etree.tostring(outAug[0], pretty_print = True, encoding = "utf8").decode("utf8"))
        f.close()

if False and __name__ == "__main__":
    #TestHeader()
    #TestXpath()
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    Test(); sys.exit(0)

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
        s = GetArg("stripDictScrap")
        stripDictScrap = (3 if s == "3" else 2 if s == "2" else 1 if s == "true" or s == "1" else 0)
        callParams["stripDictScrap"] = stripDictScrap
        callParams["stripHeader"] = (GetArg("stripHeader") == "true")
        callParams["returnFirstEntryOnly"] = (GetArg("firstEntryOnly") == "true")
        callParams["promoteNestedEntries"] = (GetArg("promoteNestedEntries") == "true")
        TransferArg("headerTitle"); TransferArg("headerPublisher"); TransferArg("headerBibl")
        #for name in params: print("param %s" % repr(name))
        print(list(name for name in params))
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

if __name__ == "__main__":
    if "--runserver" in sys.argv or "--runServer" in sys.argv:
        wsgi.server(eventlet.listen(("localhost", 8101)), MyWsgiHandler)
        sys.exit(0)

r"""
d:\users\janez\dev\misc\RelaxNg\jing-trang-master\build>.\example.bat
"""