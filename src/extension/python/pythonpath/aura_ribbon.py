"""Aura ribbon helpers shared by the build (tools/build_ribbon.py) and the
extension at run time (python/aura.py): pure ElementTree, no UNO.

* split_tab()       moves sections of a crowded tab into a new themed tab;
* extensions_page() rebuilds the Extensions tab as one labelled group per
                    installed extension (plus a "Manage" group).
"""
import copy
import gettext
import os
import re
import xml.etree.ElementTree as ET

TAB_CONTROL = "sfxlo-NotebookbarTabControl"
TOOLBOX = "sfxlo-NotebookbarToolBox"


def commands(element, visible_only=False):
    """.uno: and add-on commands under element (optionally skipping hidden widgets)."""
    out = set()

    def walk(e, hidden):
        if e.tag == "object":
            vis = next((p for p in e.findall("property") if p.get("name") == "visible"), None)
            hidden = hidden or (vis is not None and vis.text == "False")
            for p in e.findall("property"):
                if p.get("name") in ("action_name", "action-name") and (p.text or "").startswith(".uno:"):
                    if not (visible_only and hidden):
                        out.add(p.text)
        for child in e:
            walk(child, hidden)

    walk(element, False)
    return out


def tab_control(root):
    return next(o for o in root.iter("object") if o.get("class") == TAB_CONTROL)


def tab_pairs(root):
    """[(page <child>, tab <child>, label id)] in notebookbar order."""
    kids = tab_control(root).findall("child")
    return [(page, tab, next(tab.iter("object")).get("id")) for page, tab in zip(kids[0::2], kids[1::2])]


def tab_pages(root):
    return {label: page for page, _tab, label in tab_pairs(root)}


def _prop(obj, name, value=None, **attrs):
    prop = next((p for p in obj.findall("property") if p.get("name") == name), None)
    if prop is None:
        prop = ET.SubElement(obj, "property", name=name)
    prop.attrib.update(attrs)
    if value is not None:
        prop.text = value
    return prop


def _set_label(tab_child, label_id, label):
    """label: (msgctxt, msgid) translated through LibreOffice's catalog, or plain text."""
    obj = next(tab_child.iter("object"))
    obj.set("id", label_id)
    if isinstance(label, (list, tuple)):
        context, msgid = label
        _prop(obj, "label", msgid, translatable="yes", context=context)
    else:
        prop = _prop(obj, "label", label)
        for attr in ("translatable", "context"):
            prop.attrib.pop(attr, None)


def _merged_box(page_child):
    return next(o for o in page_child.iter("object") if o.get("class") == "sfxlo-PriorityMergedHBox")


def split_tab(root, source, new_id, label, sections, drop=()):
    """Move `sections` (section ids) of tab `source` into a new tab `new_id`,
    inserted right after it; `drop` sections are removed (duplicates).
    With new_id None, only drops."""
    control = tab_control(root)
    pairs = tab_pairs(root)
    index = next(i for i, (_p, _t, lid) in enumerate(pairs) if lid == source)
    page, tab, _ = pairs[index]
    box = _merged_box(page)
    if new_id is None:
        for child in list(box.findall("child")):
            obj = child.find("object")
            if obj is not None and obj.get("id") in set(drop):
                box.remove(child)
        return

    new_page = copy.deepcopy(page)
    wrapper = new_page.find("object")
    # keep only the section container; the source tab keeps its menu button
    for child in list(wrapper.findall("child")):
        if child.find("object") is None or child.find("object").get("class") != "sfxlo-PriorityMergedHBox":
            wrapper.remove(child)
    for obj in new_page.iter("object"):
        if obj.get("id"):
            obj.set("id", f"{obj.get('id')}-aura-{new_id}")
    new_box = _merged_box(new_page)
    for child in list(new_box.findall("child")):
        new_box.remove(child)

    wanted, dropped = set(sections), set(drop)
    for child in list(box.findall("child")):
        obj = child.find("object")
        sid = obj.get("id") if obj is not None else None
        if sid in wanted:
            box.remove(child)
            new_box.append(child)
        elif sid in dropped:
            box.remove(child)
    if not new_box.findall("child"):   # none of these sections in this LibreOffice version
        return False

    new_tab = copy.deepcopy(tab)
    _set_label(new_tab, new_id, label)
    kids = list(control)
    pos = kids.index(tab) + 1
    control.insert(pos, new_page)
    control.insert(pos + 1, new_tab)
    return True


class RibbonError(Exception):
    """The stock ribbon of this LibreOffice version cannot be customised safely."""


def customize(root, spec):
    """Apply a design/ribbon.json module spec to a stock notebookbar_compact.ui tree.

    Tolerant of other LibreOffice versions: a tab or section that does not
    exist is skipped. Raises RibbonError when the result would hide any
    command the stock ribbon shows (the caller then keeps the stock ribbon).
    Returns the labels of the tabs added.
    """
    try:
        tab_control(root)
    except StopIteration:
        raise RibbonError("no notebookbar tab control")
    fixes = spec.get("fix", {})
    original = {fixes.get(c, c) for c in commands(root, visible_only=True)}
    for prop in root.iter("property"):
        if prop.get("name") in ("action_name", "action-name") and prop.text in fixes:
            prop.text = fixes[prop.text]
    pages = tab_pages(root)
    home = pages.get(spec.get("home"))
    if home is not None:
        hide = set(spec.get("hide", ()))
        for obj in home.iter("object"):
            actions = {p.text for p in obj.findall("property")
                       if p.get("name") in ("action_name", "action-name")}
            if actions & hide:
                _prop(obj, "visible", "False")
    added = []
    for split in spec.get("split", []):
        if split["from"] not in tab_pages(root):
            continue
        if "id" in split:
            if split_tab(root, split["from"], split["id"], split["label"], split["sections"],
                         split.get("drop", ())):
                added.append(split["label"][1].replace("~", "").replace("_", ""))
        else:
            split_tab(root, split["from"], None, None, (), split["drop"])
    missing = original - commands(root, visible_only=True)
    if missing:
        raise RibbonError("commands would leave the ribbon: " + ", ".join(sorted(missing)))
    return added


# ------------------------------------------------------------ Extensions tab
def _object(cls, oid, **props):
    obj = ET.Element("object", {"class": cls, "id": oid})
    for k, v in {"visible": "True", "can_focus": "False", **props}.items():
        _prop(obj, k, v)
    return obj


def _child(obj, **packing):
    child = ET.Element("child")
    child.append(obj)
    if packing:
        pack = ET.SubElement(child, "packing")
        for k, v in packing.items():
            ET.SubElement(pack, "property", name=k).text = v
    return child


def _buttons_group(gid, title, items):
    """One row: muted group title, then a flat text button per command."""
    box = _object("GtkBox", f"aura-ext-{gid}", valign="center", spacing="2",
                  margin_start="4", margin_end="8")
    caption = _object("GtkLabel", f"aura-ext-{gid}-title", label=title.upper(), valign="center",
                      margin_end="4")
    box.append(_child(caption, expand="False", fill="True", position="0"))
    for n, (url, text) in enumerate(items, start=1):
        button = _object("GtkButton", f"aura-ext-{gid}-{n}", label=text, action_name=url,
                         relief="none", valign="center", can_focus="True",
                         receives_default="False", focus_on_click="False")
        box.append(_child(button, expand="False", fill="True", position=str(n)))
    return box, None


def _menu_group(gid, title, items):
    """A single 'Title ▾' button opening the group's commands."""
    menu_id = f"Menu aura-ext-{gid}"
    menu = _object("GtkMenu", menu_id)
    for n, (url, text) in enumerate(items):
        item = _object("GtkMenuItem", f"aura-ext-{gid}-m{n}", label=text, action_name=url,
                       use_underline="False")
        menu.append(_child(item))
    button = _object("svtlo-ManagedMenuButton", f"aura-ext-{gid}:{menu_id}", label=title,
                     valign="center", relief="none", can_focus="True", receives_default="False",
                     focus_on_click="False", use_underline="False")
    return button, menu


def _width(title, items):
    """Rough rendered width (px) of a buttons group, to decide when to fold it."""
    return 7 * len(title) + 20 + sum(7 * len(t) + 18 for _u, t in items)


def extensions_page(root, groups, manage_title, manage_items, budget=1500,
                    extension_label="ExtensionLabel"):
    """Replace the add-on merge point of the Extensions tab with one group per extension.

    groups: [(title, [(command URL, text), ...]), ...] already filtered for this module.
    Groups are shown as flat text buttons; when everything would not fit in
    `budget` pixels, the widest groups fold into a 'Title ▾' menu, so every
    command stays visible without the overflow chevron.
    """
    page = tab_pages(root)[extension_label]
    box = _merged_box(page)
    for child in list(box.findall("child")):
        box.remove(child)
    all_groups = [(t, i) for t, i in [(manage_title, manage_items)] + list(groups) if i]
    folded = set()
    widths = {n: _width(t, i) for n, (t, i) in enumerate(all_groups)}
    while sum(140 if n in folded else w for n, w in widths.items()) > budget:
        candidates = [n for n in widths if n not in folded and n != 0]
        if not candidates:
            break
        folded.add(max(candidates, key=widths.get))
    for n, (title, items) in enumerate(all_groups):
        build = _menu_group if n in folded else _buttons_group
        widget, menu = build(str(n), title, items)
        if menu is not None:
            root.insert(0, menu)
        box.append(_child(widget, expand="False", fill="True", position=str(2 * n)))
        sep = _object("GtkSeparator", f"aura-ext-sep-{n}", orientation="vertical",
                      margin_top="8", margin_bottom="8")
        box.append(_child(sep, expand="False", fill="True", position=str(2 * n + 1)))


# ---------------------------------------------------------------- language
DOMAINS = {"swriter": "sw", "scalc": "sc", "simpress": "sd", "sdraw": "sd"}


def catalog(resource_dir, lang, domain):
    """LibreOffice's own translations for a UI language (None for en-US / not installed)."""
    for tag in (lang, lang.split("-")[0]):
        path = os.path.join(resource_dir, tag, "LC_MESSAGES", domain + ".mo")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return gettext.GNUTranslations(f)
    return None


def localize(root, module, lang, resource_dir, overrides):
    """Write final label texts for the UI language.

    Aura's own tabs (ids starting with 'Aura') carry a [msgctxt, msgid] that
    LibreOffice already translates; they get the translation with the
    mnemonic marker removed. `overrides` ({translation context key: text}) fix
    stock labels for this language (e.g. French 'Origine' -> 'Accueil').
    """
    cat = catalog(resource_dir, lang, DOMAINS[module])
    for obj in root.iter("object"):
        for prop in obj.findall("property"):
            if prop.get("name") != "label":
                continue
            key = (prop.get("context") or "").rpartition("|")[2]
            text = None
            if key in overrides:
                text = overrides[key]
            elif (obj.get("id") or "").startswith("Aura") and prop.get("translatable") == "yes":
                msgid = prop.text or ""
                text = cat.pgettext(prop.get("context"), msgid) if cat else msgid
                text = text.replace("_", "")
            if text is not None:
                prop.text = text
                for attr in ("translatable", "context"):
                    prop.attrib.pop(attr, None)


def pretty_name(node):
    """'Zotero.OfficeToolBar' -> 'Zotero', 'textToSpeech.OfficeNotebookBar' -> 'Text To Speech'."""
    base = re.sub(r"(?i)[._](office)?(toolbar|notebookbar|menubar)(merging)?$", "", node)
    base = re.sub(r"(?i)[._](toolbar|notebookbar|extension|addon|addons)$", "", base)
    part = base.split(".")[-1] or base
    part = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).replace("_", " ")
    return part[:1].upper() + part[1:]


def group_key(node):
    return re.sub(r"(?i)[._](office)?(toolbar|notebookbar|menubar)(merging)?$", "", node).lower()
