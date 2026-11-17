# -*- coding: utf-8 -*-
"""
Reveal Codes for LibreOffice Writer - sidebar panel.

Shows the formatting "codes" around your cursor, WordPerfect style, in a
live sidebar panel. Click a code to select it, then:
  * Delete code          removes that one code
  * Delete all like this removes every matching code in the document (one Undo)
  * Find next / previous jumps the cursor to the next/previous matching code
Click a word to move the document cursor there.

The labels follow Tools > Options > Language Settings > Languages > Locale setting
(language only, no dialects: English is Canadian, French is France, ...).  Words that
LibreOffice itself translates (Bold, Page Break, ...) are borrowed from its own menus
when the interface language matches; otherwise built-in translations are used.
"""

import json
import os
import re
import tempfile
import threading
import time
import traceback

import uno
import unohelper

from com.sun.star.awt import (FontDescriptor, Rectangle, WindowDescriptor,
                              XKeyListener, XMouseListener, XPaintListener,
                              XWindowListener)
from com.sun.star.ui import (LayoutSize, XSidebarPanel, XToolPanel,
                             XUIElement, XUIElementFactory)

IMPL_NAME = "org.revealcodes.PanelFactory"
BEFORE_MAX, AFTER_MAX = 12, 14    # most paragraphs shown before / after the current one
TOKEN_BUDGET = 260                # stop adding paragraphs once this many pieces are collected per side
SPACE_MARK = u"·"            # middle dot, shows a space


def _log(msg):
    try:
        with open(os.path.join(tempfile.gettempdir(), "revealcodes.log"), "a") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


# =====================================================================
#  Language
# =====================================================================

EN = {
    "bold": "Bold", "italic": "Italic", "underline": "Underline", "strike": "Strikeout",
    "sup": "Superscript", "sub": "Subscript", "link": "Link",
    "font": "Font", "size": "Size", "colour": "Colour", "auto": "Auto",
    "style": "Style", "default": "Default", "just": "Just",
    "left": "Left", "right": "Right", "full": "Full", "centre": "Centre",
    "indent": "Indent", "rmar": "R Mar", "first": "1st Line", "above": "Spc Above",
    "below": "Spc Below", "lnspc": "Ln Spc", "list": "List",
    "hpg": "HPg", "colbrk": "Col Brk", "tab": "Tab", "hrt": "HRt", "hrtline": "HRt-line",
    "spg": "SPg", "footnote": "Footnote", "field": "Field", "object": "Object",
    "ruby": "Ruby", "change": "Change", "tblcell": "Tbl Cell",
    "on": "%s On", "off": "%s Off",
    "b_delete": "Delete code", "b_delall": "Delete all like this",
    "b_next": "Find next", "b_prev": "Find previous",
    "hint": "Click a code, then Delete", "loading": "Loading...",
    "only_writer": "Reveal Codes works in Writer documents.",
    "no_para": "(cursor is not in a normal paragraph)",
    "err_delete": "Could not delete: %s", "nothing": "Nothing to delete",
    "nomatch": "No other “%s” found", "wrapped": "Wrapped around the document",
    "found": "Found: %s", "searching": "Searching...",
    "confirm": "Delete all %(n)d codes like “%(c)s”?\n\nYou can undo this with Edit > Undo.",
    "deleted": "Deleted %d codes", "no_hrt_all": "Paragraph ends can’t be deleted all at once",
    "undo_title": "Delete all codes like this",
}

# Words LibreOffice already translates in its own menus: key -> command.
LO_COMMANDS = {
    "bold": ".uno:Bold", "italic": ".uno:Italic", "underline": ".uno:Underline",
    "strike": ".uno:Strikeout", "sup": ".uno:SuperScript", "sub": ".uno:SubScript",
    "link": ".uno:HyperlinkDialog", "font": ".uno:CharFontName", "size": ".uno:FontHeight",
    "colour": ".uno:Color", "style": ".uno:StyleApply", "left": ".uno:LeftPara",
    "right": ".uno:RightPara", "centre": ".uno:CenterPara", "full": ".uno:JustifyPara",
    "hpg": ".uno:InsertPagebreak", "colbrk": ".uno:InsertColumnBreak",
    "footnote": ".uno:InsertFootnote", "lnspc": ".uno:LineSpacing",
    "b_next": ".uno:DownSearch", "b_prev": ".uno:UpSearch",
}

# First-pass translations of the remaining terms (everything else falls back to English).
# These are mine and should be checked by a native speaker.
OWN = {
    "fr": {"tab": "Tab", "hrt": "Ret", "hrtline": "Ret-ligne", "spg": "Saut pg", "field": "Champ",
           "object": "Objet", "ruby": "Ruby", "change": "Modif.", "tblcell": "Cell. tabl.",
           "auto": "Auto", "default": "Défaut", "just": "Justif", "indent": "Retrait",
           "rmar": "Marge dr", "first": "1re ligne", "above": "Esp avant", "below": "Esp après",
           "list": "Liste", "b_delete": "Supprimer le code", "b_delall": "Supprimer tous les semblables",
           "hint": "Cliquez sur un code, puis Supprimer", "loading": "Chargement...",
           "only_writer": "Révéler les codes fonctionne dans les documents Writer.",
           "no_para": "(le curseur n’est pas dans un paragraphe normal)",
           "err_delete": "Suppression impossible : %s", "nothing": "Rien à supprimer",
           "nomatch": "Aucun autre « %s » trouvé", "wrapped": "Retour au début du document",
           "found": "Trouvé : %s", "searching": "Recherche...",
           "confirm": "Supprimer les %(n)d codes semblables à « %(c)s » ?\n\nVous pouvez annuler avec Édition > Annuler.",
           "deleted": "%d codes supprimés", "no_hrt_all": "Les fins de paragraphe ne peuvent pas être supprimées en bloc",
           "undo_title": "Supprimer tous les codes semblables"},
    "de": {"tab": "Tab", "hrt": "Absatz", "hrtline": "Zeilenumbruch", "spg": "Weicher Umbr.", "field": "Feld",
           "object": "Objekt", "ruby": "Ruby", "change": "Änderung", "tblcell": "Tab.-Zelle",
           "auto": "Automatisch", "default": "Standard", "just": "Ausr.", "indent": "Einzug",
           "rmar": "Rechter Rand", "first": "Erstzeile", "above": "Abst. oben", "below": "Abst. unten",
           "list": "Liste", "b_delete": "Code löschen", "b_delall": "Alle gleichen löschen",
           "hint": "Code anklicken, dann Löschen", "loading": "Wird geladen...",
           "only_writer": "Codes anzeigen funktioniert in Writer-Dokumenten.",
           "no_para": "(Cursor steht nicht in einem normalen Absatz)",
           "err_delete": "Löschen nicht möglich: %s", "nothing": "Nichts zu löschen",
           "nomatch": "Kein weiteres „%s“ gefunden", "wrapped": "Am Dokumentanfang fortgesetzt",
           "found": "Gefunden: %s", "searching": "Suche...",
           "confirm": "Alle %(n)d Codes wie „%(c)s“ löschen?\n\nSie können dies mit Bearbeiten > Rückgängig widerrufen.",
           "deleted": "%d Codes gelöscht", "no_hrt_all": "Absatzenden können nicht alle auf einmal gelöscht werden",
           "undo_title": "Alle gleichen Codes löschen"},
    "es": {"tab": "Tab", "hrt": "Intro", "hrtline": "Salto línea", "spg": "Salto pág. suave", "field": "Campo",
           "object": "Objeto", "ruby": "Ruby", "change": "Cambio", "tblcell": "Celda tabla",
           "auto": "Auto", "default": "Predeterminado", "just": "Just.", "indent": "Sangría",
           "rmar": "Marg. der.", "first": "1.ª línea", "above": "Esp. antes", "below": "Esp. después",
           "list": "Lista", "b_delete": "Eliminar código", "b_delall": "Eliminar todos los iguales",
           "hint": "Haga clic en un código y luego en Eliminar", "loading": "Cargando...",
           "only_writer": "Mostrar códigos funciona en documentos de Writer.",
           "no_para": "(el cursor no está en un párrafo normal)",
           "err_delete": "No se pudo eliminar: %s", "nothing": "Nada que eliminar",
           "nomatch": "No hay otro «%s»", "wrapped": "Se volvió al inicio del documento",
           "found": "Encontrado: %s", "searching": "Buscando...",
           "confirm": "¿Eliminar los %(n)d códigos como «%(c)s»?\n\nPuede deshacerlo con Editar > Deshacer.",
           "deleted": "%d códigos eliminados", "no_hrt_all": "Los finales de párrafo no se pueden eliminar todos a la vez",
           "undo_title": "Eliminar todos los códigos iguales"},
    "it": {"tab": "Tab", "hrt": "Invio", "hrtline": "A capo", "spg": "Salto pag. auto", "field": "Campo",
           "object": "Oggetto", "ruby": "Ruby", "change": "Modifica", "tblcell": "Cella tab.",
           "auto": "Auto", "default": "Predefinito", "just": "Giust.", "indent": "Rientro",
           "rmar": "Marg. dx", "first": "1ª riga", "above": "Spaz. sopra", "below": "Spaz. sotto",
           "list": "Elenco", "b_delete": "Elimina codice", "b_delall": "Elimina tutti gli uguali",
           "hint": "Fai clic su un codice, poi Elimina", "loading": "Caricamento...",
           "only_writer": "Mostra codici funziona nei documenti Writer.",
           "no_para": "(il cursore non è in un paragrafo normale)",
           "err_delete": "Impossibile eliminare: %s", "nothing": "Niente da eliminare",
           "nomatch": "Nessun altro «%s» trovato", "wrapped": "Ripartito dall’inizio del documento",
           "found": "Trovato: %s", "searching": "Ricerca...",
           "confirm": "Eliminare tutti i %(n)d codici come «%(c)s»?\n\nPuoi annullare con Modifica > Annulla.",
           "deleted": "%d codici eliminati", "no_hrt_all": "Le fini paragrafo non si possono eliminare tutte insieme",
           "undo_title": "Elimina tutti i codici uguali"},
    "pt": {"tab": "Tab", "hrt": "Enter", "hrtline": "Quebra linha", "spg": "Quebra pág. auto", "field": "Campo",
           "object": "Objeto", "ruby": "Ruby", "change": "Alteração", "tblcell": "Célula tab.",
           "auto": "Auto", "default": "Padrão", "just": "Just.", "indent": "Recuo",
           "rmar": "Marg. dir.", "first": "1.ª linha", "above": "Esp. antes", "below": "Esp. depois",
           "list": "Lista", "b_delete": "Excluir código", "b_delall": "Excluir todos os iguais",
           "hint": "Clique num código e depois em Excluir", "loading": "Carregando...",
           "only_writer": "Revelar códigos funciona em documentos do Writer.",
           "no_para": "(o cursor não está num parágrafo normal)",
           "err_delete": "Não foi possível excluir: %s", "nothing": "Nada para excluir",
           "nomatch": "Nenhum outro “%s” encontrado", "wrapped": "Voltou ao início do documento",
           "found": "Encontrado: %s", "searching": "Procurando...",
           "confirm": "Excluir todos os %(n)d códigos como “%(c)s”?\n\nPode desfazer com Editar > Desfazer.",
           "deleted": "%d códigos excluídos", "no_hrt_all": "Fins de parágrafo não podem ser excluídos todos de uma vez",
           "undo_title": "Excluir todos os códigos iguais"},
    "nl": {"tab": "Tab", "hrt": "Enter", "hrtline": "Regeleinde", "spg": "Zachte pag.", "field": "Veld",
           "object": "Object", "ruby": "Ruby", "change": "Wijziging", "tblcell": "Tabelcel",
           "auto": "Auto", "default": "Standaard", "just": "Uitl.", "indent": "Inspringing",
           "rmar": "Rechtermarge", "first": "1e regel", "above": "Ruimte boven", "below": "Ruimte onder",
           "list": "Lijst", "b_delete": "Code verwijderen", "b_delall": "Alle gelijke verwijderen",
           "hint": "Klik op een code en dan op Verwijderen", "loading": "Laden...",
           "only_writer": "Codes weergeven werkt in Writer-documenten.",
           "no_para": "(cursor staat niet in een gewone alinea)",
           "err_delete": "Verwijderen mislukt: %s", "nothing": "Niets te verwijderen",
           "nomatch": "Geen andere „%s” gevonden", "wrapped": "Terug naar het begin van het document",
           "found": "Gevonden: %s", "searching": "Zoeken...",
           "confirm": "Alle %(n)d codes zoals „%(c)s” verwijderen?\n\nU kunt dit ongedaan maken met Bewerken > Ongedaan maken.",
           "deleted": "%d codes verwijderd", "no_hrt_all": "Alineaeindes kunnen niet allemaal tegelijk worden verwijderd",
           "undo_title": "Alle gelijke codes verwijderen"},
}


# Used when the Locale setting differs from the interface language (LibreOffice's own labels
# are then in the wrong language).  First-pass translations; need a native speaker's review.
_K = ("bold italic underline strike sup sub link font size colour style left right centre full "
      "hpg colbrk footnote lnspc b_next b_prev").split()
_V = {
 "fr": "Gras|Italique|Souligné|Barré|Exposant|Indice|Lien|Police|Taille|Couleur|Style|Gauche|Droite|Centré|Justifié|Saut pg|Saut col|Note|Interligne|Suivant|Précédent",
 "de": "Fett|Kursiv|Unterstr.|Durchgestr.|Hochgest.|Tiefgest.|Link|Schrift|Größe|Farbe|Vorlage|Links|Rechts|Zentriert|Blocksatz|Seitenumbr.|Spaltenumbr.|Fußnote|Zeilenabst.|Weitersuchen|Rückwärts suchen",
 "es": "Negrita|Cursiva|Subrayado|Tachado|Superíndice|Subíndice|Enlace|Fuente|Tamaño|Color|Estilo|Izquierda|Derecha|Centrado|Justificado|Salto pág.|Salto col.|Nota|Interlineado|Buscar siguiente|Buscar anterior",
 "it": "Grassetto|Corsivo|Sottolineato|Barrato|Apice|Pedice|Collegamento|Carattere|Dimensione|Colore|Stile|Sinistra|Destra|Centrato|Giustificato|Salto pag.|Salto col.|Nota|Interlinea|Trova successivo|Trova precedente",
 "pt": "Negrito|Itálico|Sublinhado|Tachado|Sobrescrito|Subscrito|Link|Fonte|Tamanho|Cor|Estilo|Esquerda|Direita|Centralizado|Justificado|Quebra pág.|Quebra col.|Nota|Espaçamento|Localizar próximo|Localizar anterior",
 "nl": "Vet|Cursief|Onderstreept|Doorgehaald|Superscript|Subscript|Koppeling|Lettertype|Grootte|Kleur|Stijl|Links|Rechts|Gecentreerd|Uitgevuld|Pagina-einde|Kolomeinde|Voetnoot|Regelafstand|Volgende zoeken|Vorige zoeken",
}
for _l, _row in _V.items():
    OWN[_l].update(dict(zip(_K, _row.split("|"))))


def _load_json(name):
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        _log("could not read %s: %s" % (name, exc))
        return {}


LO_LABELS = {}      # language -> {key: LibreOffice's own label}   (labels.json, from LibreOffice's translations)
OWN_STRINGS = {}    # language -> {key: my translation}             (strings.json)
_DIR_OVERRIDE = {"zh": "zh-CN", "no": "nb", "iw": "he", "fil": "tl", "sa": "sa-IN", "pa": "pa-IN",
                 "sw": "sw-TZ", "sat": "sat-Olck", "kmr": "kmr-Latn", "bn": "bn", "pt": "pt", "sr": "sr"}


def pick_language(lang, country):
    """Locale language -> the language folder used in LibreOffice's translations (no dialects)."""
    if lang == "zh" and country.upper() in ("TW", "HK", "MO"):
        return "zh-TW"
    return _DIR_OVERRIDE.get(lang, lang)


def _strip_label(label):
    """'~Bold...' / 'Fett(~B)' -> 'Bold' / 'Fett'."""
    if not label:
        return ""
    label = re.sub(r"\s*\(~.\)", "", label).replace("~", "")
    return label.rstrip(" .…").strip()


class Language(object):
    """Picks labels in the language of LibreOffice's Locale setting."""

    def __init__(self):
        self.lang = "en"
        self.ui_lang = None
        self.folder = "en"
        self.labels = {}
        self.country = ""
        self.dec = "."
        self.ctx = None
        self.table = {}
        self._lo = {}
        self._desc = None

    def _config(self, path, name):
        from com.sun.star.beans import PropertyValue
        cp = self.ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.configuration.ConfigurationProvider", self.ctx)
        pv = PropertyValue()
        pv.Name = "nodepath"
        pv.Value = path
        acc = cp.createInstanceWithArguments("com.sun.star.configuration.ConfigurationAccess", (pv,))
        return acc.getByName(name) or ""

    def init(self, ctx):
        """Follow Tools > Options > Language Settings > Languages > Locale setting.
        Only the language part counts (no dialects): English is always Canadian."""
        self.ctx = ctx
        loc, ui = "", ""
        try:
            loc = self._config("/org.openoffice.Setup/L10N", "ooSetupSystemLocale")   # "Locale setting"
            ui = self._config("/org.openoffice.Setup/L10N", "ooLocale")               # interface language
        except Exception as exc:
            _log("language detection failed: %s" % exc)
        if not loc:                                  # "Default": use the operating system's locale
            try:
                loc = self._config("/org.openoffice.System/L10N", "Locale")
            except Exception:
                loc = ""
        parts = (loc or ui or "en-US").replace("_", "-").split("-")
        lang = parts[0].lower() or "en"
        country = parts[1] if len(parts) > 1 else ""
        ui_lang = (ui or "en-US").replace("_", "-").split("-")[0].lower()
        changed = (lang, ui_lang) != (self.lang, getattr(self, "ui_lang", None))
        if not LO_LABELS:
            LO_LABELS.update(_load_json("labels.json"))
            OWN_STRINGS.update(_load_json("strings.json"))
        folder = pick_language(lang, country)
        self.lang, self.ui_lang = lang, ui_lang
        self.country = country
        self.folder = folder
        self.table = dict(OWN_STRINGS.get(folder) or OWN_STRINGS.get(lang) or {})
        self.table.update(OWN.get(lang, {}))
        self.labels = LO_LABELS.get(folder) or LO_LABELS.get(lang) or {}
        self._lo = {}
        self.dec = "," if lang in ("fr", "de", "es", "it", "pt", "nl", "ru", "pl", "cs", "sv", "da", "nb",
                                   "nn", "fi", "tr", "hu", "ro", "uk", "el", "bg", "sk", "sl", "hr", "sr",
                                   "lt", "lv", "et", "ca", "gl", "eu", "id", "vi") else "."
        if changed:
            _log("language: %s (locale setting %r, interface %r)" % (lang, loc, ui))
        return changed

    @property
    def english(self):
        return self.lang == "en"

    def _lo_label(self, key):
        if key in self._lo:
            return self._lo[key]
        label = ""
        cmd = LO_COMMANDS.get(key)
        if cmd and self.ctx is not None:
            try:
                if self._desc is None:
                    d = self.ctx.ServiceManager.createInstanceWithContext(
                        "com.sun.star.frame.UICommandDescription", self.ctx)
                    self._desc = d.getByName("com.sun.star.text.TextDocument")
                item = self._desc.getByName(cmd)
                for prop in item:
                    if prop.Name == "Label":
                        label = _strip_label(prop.Value)
            except Exception:
                label = ""
        self._lo[key] = label
        return label

    def t(self, key):
        if self.english:
            return EN[key]
        return self.labels.get(key) or self.table.get(key) or EN[key]

    def on(self, key):
        name = self.t(key)
        return (EN["on"] % name) if self.english else (u"+ " + name)

    def off(self, key):
        name = self.t(key)
        return (EN["off"] % name) if self.english else (u"− " + name)

    def num(self, text):
        return text.replace(".", self.dec) if self.dec != "." else text


L = Language()


# =====================================================================
#  Reading the document into tokens
# =====================================================================

class Tok(object):
    """One thing to draw: a code box, a piece of text, the cursor, ..."""
    __slots__ = ("kind", "text", "pos", "action", "key")

    def __init__(self, kind, text, pos=None, action=None, key=None):
        self.kind = kind        # code | hrt | text | cursor | gap
        self.text = text        # what is drawn (in the interface language)
        self.pos = pos          # (XTextRange, char offset) used to move the cursor
        self.action = action    # tuple describing how to delete this code, or None
        self.key = key          # language-independent identity, used by Find / Delete all


def family(key):
    """On/Off pairs belong together when deleting: 'T:Bold:on' and 'T:Bold:off' -> 'T:Bold'."""
    if key and key.startswith("T:"):
        return key.rsplit(":", 1)[0]
    return key


def _get(obj, name, default=None):
    try:
        value = getattr(obj, name)
        return default if value is None else value
    except Exception:
        return default


def _is_italic(posture):
    value = getattr(posture, "value", posture)
    return str(value) not in ("NONE", "0", "None")


def _cstate(o):
    esc = _get(o, "CharEscapement", 0) or 0
    return {
        "Bold": _get(o, "CharWeight", 100) >= 150,
        "Italic": _is_italic(_get(o, "CharPosture", 0)),
        "Underline": _get(o, "CharUnderline", 0) != 0,
        "Strike": _get(o, "CharStrikeout", 0) != 0,
        "Sup": esc > 0,
        "Sub": esc < 0,
        "Link": bool(_get(o, "HyperLinkURL", "")),
        "Font": _get(o, "CharFontName", ""),
        "Size": _get(o, "CharHeight", 0),
        "Color": _get(o, "CharColor", -1),
    }


TOGGLES = [("Bold", "bold"), ("Italic", "italic"), ("Underline", "underline"),
           ("Strike", "strike"), ("Sup", "sup"), ("Sub", "sub"),
           ("Link", "link")]
VALUE_KEYS = ["Font", "Size", "Color"]

RESET_PROPS = {
    "Bold": ["CharWeight"],
    "Italic": ["CharPosture"],
    "Underline": ["CharUnderline"],
    "Strike": ["CharStrikeout"],
    "Sup": ["CharEscapement", "CharEscapementHeight"],
    "Sub": ["CharEscapement", "CharEscapementHeight"],
    "Font": ["CharFontName", "CharFontStyleName"],
    "Size": ["CharHeight"],
    "Color": ["CharColor"],
}


def _value_label(key, value):
    if key == "Font":
        return "%s:%s" % (L.t("font"), value)
    if key == "Size":
        return "%s:%s" % (L.t("size"), L.num("%gpt" % value))
    if key == "Color":
        shown = L.t("auto") if value == -1 else "#%06X" % (value & 0xFFFFFF)
        return "%s:%s" % (L.t("colour"), shown)
    return key


def _inch(v):
    return L.num('%.2f"' % (v / 2540.0))


ADJUST_KEYS = {0: "left", 1: "right", 2: "full", 3: "centre"}
PARA_SPACING_PROPS = [("ParaLeftMargin", "indent"), ("ParaRightMargin", "rmar"),
                      ("ParaFirstLineIndent", "first"), ("ParaTopMargin", "above"),
                      ("ParaBottomMargin", "below")]


def _para_codes(doc, para, style):
    """Paragraph-level codes: (label, key, action) triples."""
    codes = []
    if para.ParaStyleName == "Standard":
        shown = L.t("default")
    else:
        shown = _get(style, "DisplayName", para.ParaStyleName)
    codes.append(("%s:%s" % (L.t("style"), shown), "Style:%s" % para.ParaStyleName,
                  ("pstyle", para)))

    adj, sadj = _get(para, "ParaAdjust"), _get(style, "ParaAdjust")
    if adj is not None and adj != sadj:
        name = L.t(ADJUST_KEYS[adj]) if adj in ADJUST_KEYS else str(adj)
        codes.append(("%s:%s" % (L.t("just"), name), "Just:%s" % adj, ("pprop", para, ["ParaAdjust"])))

    for prop, lk in PARA_SPACING_PROPS:
        v, sv = _get(para, prop), _get(style, prop)
        if v is not None and sv is not None and v != sv:
            codes.append(("%s:%s" % (L.t(lk), _inch(v)), "%s:%s" % (lk, v), ("pprop", para, [prop])))

    ls, sls = _get(para, "ParaLineSpacing"), _get(style, "ParaLineSpacing")
    if ls is not None and sls is not None and (ls.Mode, ls.Height) != (sls.Mode, sls.Height):
        if ls.Mode == 0:
            label = "%s:%s" % (L.t("lnspc"), L.num("%d%%" % ls.Height))
        else:
            label = "%s:%s" % (L.t("lnspc"), _inch(ls.Height))
        codes.append((label, "LnSpc:%s:%s" % (ls.Mode, ls.Height), ("pprop", para, ["ParaLineSpacing"])))

    ll = _get(para, "ListLabelString", "")
    if ll:
        codes.append(("%s:%s" % (L.t("list"), ll), "List", ("list", para)))
    return codes


def _break_type(para):
    bt = _get(para, "BreakType")
    return str(getattr(bt, "value", "NONE"))


def _chunks(text):
    """Split text into tabs, words (with trailing spaces) and space runs."""
    return [(m.group(0), m.start()) for m in re.finditer(r"\t|[^\t ]+ *| +", text)]


def para_tokens(doc, para, cursor_offset=None, full=False):
    toks = []
    styles = doc.StyleFamilies.getByName("ParagraphStyles")
    style = styles.getByName(para.ParaStyleName)
    base = _cstate(style)

    pstart = para.getStart()
    if _break_type(para) in ("PAGE_BEFORE", "PAGE_BOTH"):
        toks.append(Tok("code", L.t("hpg"), pos=(pstart, 0), action=("break", para), key="HPg"))
    if _break_type(para) in ("COLUMN_BEFORE", "COLUMN_BOTH"):
        toks.append(Tok("code", L.t("colbrk"), pos=(pstart, 0), action=("break", para), key="ColBrk"))

    for label, key, action in _para_codes(doc, para, style):
        toks.append(Tok("code", label, pos=(pstart, 0), action=action, key=key))

    if full:
        lo, hi = -1, 1 << 40                    # whole-document scan: look at everything
    elif cursor_offset is None:
        lo, hi = 0, 500                         # other paragraphs: show their beginning
    else:
        lo, hi = cursor_offset - 600, cursor_offset + 600
    current = dict(base)
    open_spans = {}                     # toggle key -> [start_range, [tokens]]
    value_tokens = {}                   # value key -> (start_range, token)
    pos = 0
    marked = False
    para_end = para.getEnd()
    portions = para.createEnumeration()

    def close_value(key, end_range):
        if key in value_tokens:
            start, tok = value_tokens.pop(key)
            tok.action = ("span", key, start, end_range)

    while portions.hasMoreElements():
        p = portions.nextElement()
        ptype = p.TextPortionType
        text = p.String or ""
        start = p.getStart()

        if ptype == "Text":
            new = _cstate(p)
            for key, name in TOGGLES:
                if current[key] != new[key]:
                    if new[key]:
                        tok = Tok("code", L.on(name), pos=(start, 0), key="T:%s:on" % key)
                        open_spans[key] = [start, [tok]]
                        toks.append(tok)
                    else:
                        tok = Tok("code", L.off(name), pos=(start, 0), key="T:%s:off" % key)
                        toks.append(tok)
                        if key in open_spans:
                            s, group = open_spans.pop(key)
                            group.append(tok)
                            act = ("span", key, s, start)
                            for t in group:
                                t.action = act
            for key in VALUE_KEYS:
                if current[key] != new[key]:
                    close_value(key, start)
                    tok = Tok("code", _value_label(key, new[key]), pos=(start, 0),
                              key="V:%s:%s" % (key, new[key]))
                    toks.append(tok)
                    value_tokens[key] = (start, tok)
            current = new

            length = len(text)
            co = cursor_offset
            here = (co is not None and not marked and pos <= co <= pos + length)
            chunks = _chunks(text)
            skipping = False
            if here and not chunks:
                toks.append(Tok("cursor", "", pos=(start, 0)))
                marked = True
            for chunk, off in chunks:
                end = off + len(chunk)
                a = pos + off
                if a + len(chunk) < lo or a > hi:
                    if not skipping:
                        toks.append(Tok("text", u"\u2026", pos=(start, off)))
                        skipping = True
                    continue
                skipping = False
                if here and not marked and co - pos <= off:
                    toks.append(Tok("cursor", "", pos=(start, off)))
                    marked = True
                if chunk == "\t":
                    toks.append(Tok("code", L.t("tab"), pos=(start, off),
                                    action=("chars", start, off, 1), key="Tab"))
                elif here and not marked and off < co - pos < end:
                    cut = co - pos - off
                    toks.append(Tok("text", chunk[:cut].replace(" ", SPACE_MARK), pos=(start, off)))
                    toks.append(Tok("cursor", "", pos=(start, off + cut)))
                    marked = True
                    toks.append(Tok("text", chunk[cut:].replace(" ", SPACE_MARK), pos=(start, off + cut)))
                else:
                    toks.append(Tok("text", chunk.replace(" ", SPACE_MARK), pos=(start, off)))
            if here and not marked:
                toks.append(Tok("cursor", "", pos=(start, length)))
                marked = True
            pos += length
        else:
            lk = {"LineBreak": "hrtline", "SoftPageBreak": "spg", "Footnote": "footnote",
                  "TextField": "field", "Frame": "object", "DrawingLayerAnchor": "object",
                  "Ruby": "ruby", "Redline": "change"}.get(ptype)
            if lk:
                toks.append(Tok("code", L.t(lk), pos=(start, 0), key=lk))
            elif text:
                toks.append(Tok("text", text, pos=(start, 0)))
            pos += len(text)

    # close anything still open at the end of the paragraph
    for key, name in TOGGLES:
        if key in open_spans:
            s, group = open_spans.pop(key)
            tok = Tok("code", L.off(name), pos=(para_end, 0), key="T:%s:off" % key)
            toks.append(tok)
            group.append(tok)
            act = ("span", key, s, para_end)
            for t in group:
                t.action = act
    for key in list(value_tokens):
        close_value(key, para_end)

    if cursor_offset is not None and not marked:
        toks.append(Tok("cursor", "", pos=(para_end, 0)))

    toks.append(Tok("hrt", L.t("hrt"), pos=(para_end, 0), action=("hrt", para_end), key="HRt"))
    if _break_type(para) in ("PAGE_AFTER", "PAGE_BOTH"):
        toks.append(Tok("code", L.t("hpg"), pos=(para_end, 0), action=("break", para), key="HPg"))
    if _break_type(para) in ("COLUMN_AFTER", "COLUMN_BOTH"):
        toks.append(Tok("code", L.t("colbrk"), pos=(para_end, 0), action=("break", para), key="ColBrk"))
    toks.append(Tok("gap", ""))
    return toks


def _paragraph_at(cursor):
    cursor.gotoStartOfParagraph(False)
    cursor.gotoEndOfParagraph(True)
    paras = cursor.createEnumeration()
    if not paras.hasMoreElements():
        return None
    para = paras.nextElement()
    return para if hasattr(para, "ParaStyleName") else None


def build_tokens(doc):
    """Tokens for the paragraphs around the view cursor."""
    view_cursor = doc.CurrentController.getViewCursor()
    text = view_cursor.getText()
    here = view_cursor.getStart()

    probe = text.createTextCursorByRange(here)
    probe.gotoStartOfParagraph(True)
    offset = len(probe.String)

    current_para = _paragraph_at(text.createTextCursorByRange(here))
    if current_para is None:
        return [Tok("text", L.t("no_para"))]

    toks = []
    cell = _get(view_cursor, "Cell")
    if cell is not None:
        toks.append(Tok("code", "%s:%s" % (L.t("tblcell"), _get(cell, "CellName", "?"))))
        toks.append(Tok("gap", ""))

    before = []
    used = 0
    c = text.createTextCursorByRange(here)
    c.gotoStartOfParagraph(False)
    for _ in range(BEFORE_MAX):
        if used > TOKEN_BUDGET or not c.gotoPreviousParagraph(False):
            break
        para = _paragraph_at(text.createTextCursorByRange(c.getStart()))
        if para is not None:
            group = para_tokens(doc, para)
            used += len(group)
            before.insert(0, group)
    for group in before:
        toks.extend(group)

    toks.extend(para_tokens(doc, current_para, offset))

    used = 0
    c = text.createTextCursorByRange(here)
    c.gotoEndOfParagraph(False)
    for _ in range(AFTER_MAX):
        if used > TOKEN_BUDGET or not c.gotoNextParagraph(False):
            break
        para = _paragraph_at(text.createTextCursorByRange(c.getStart()))
        if para is not None:
            group = para_tokens(doc, para)
            used += len(group)
            toks.extend(group)
    return toks


def signature(toks):
    return tuple((t.kind, t.text) for t in toks)


# =====================================================================
#  Deleting a code
# =====================================================================

def apply_action(action):
    """Remove the formatting a code stands for. Returns an error text or None."""
    try:
        kind = action[0]
        if kind == "pprop":
            _, para, props = action
            for prop in props:
                para.setPropertyToDefault(prop)
        elif kind == "pstyle":
            action[1].ParaStyleName = "Standard"
        elif kind == "break":
            action[1].BreakType = uno.Enum("com.sun.star.style.BreakType", "NONE")
        elif kind == "list":
            action[1].NumberingStyleName = ""
        elif kind == "span":
            _, key, start, end = action
            text = start.getText()
            c = text.createTextCursorByRange(start)
            c.gotoRange(end, True)
            if key == "Link":
                c.HyperLinkURL = ""
                c.HyperLinkTarget = ""
                c.HyperLinkName = ""
            else:
                for prop in RESET_PROPS[key]:
                    try:
                        c.setPropertyToDefault(prop)
                    except Exception:
                        pass
        elif kind == "chars":
            _, rng, off, n = action
            text = rng.getText()
            c = text.createTextCursorByRange(rng)
            c.goRight(off, False)
            c.goRight(n, True)
            c.String = ""
        elif kind == "hrt":
            rng = action[1]
            text = rng.getText()
            c = text.createTextCursorByRange(rng)
            if c.goRight(1, True):
                c.String = ""
        return None
    except Exception as exc:
        _log("apply_action failed: %s\n%s" % (exc, traceback.format_exc()))
        return str(exc)


def move_cursor_to(doc, pos):
    rng, off = pos
    text = rng.getText()
    c = text.createTextCursorByRange(rng)
    if off:
        c.goRight(off, False)
    doc.CurrentController.getViewCursor().gotoRange(c.getStart(), False)


# =====================================================================
#  Whole-document work: find a code, delete all like it
# =====================================================================

def scan_document(doc):
    """Every code in the document, in order: [(paragraph, [code tokens])]."""
    out = []

    def walk(enum):
        while enum.hasMoreElements():
            el = enum.nextElement()
            try:
                if el.supportsService("com.sun.star.text.Paragraph"):
                    toks = para_tokens(doc, el, None, full=True)
                    out.append((el, [t for t in toks if t.key]))
                elif el.supportsService("com.sun.star.text.TextTable"):
                    for name in el.getCellNames():
                        walk(el.getCellByName(name).createEnumeration())
            except Exception as exc:
                _log("scan skipped an element: %s" % exc)

    walk(doc.Text.createEnumeration())
    return out


def _tok_range(tok):
    rng, off = tok.pos
    c = rng.getText().createTextCursorByRange(rng)
    if off:
        c.goRight(off, False)
    return c.getStart()


def _in_para(para, here):
    """Is this text position inside that paragraph?  (False if they live in different texts.)"""
    try:
        text = para.getText()
        return (text.compareRegionStarts(para.getStart(), here) >= 0
                and text.compareRegionStarts(here, para.getEnd()) >= 0)
    except Exception:
        return False


def find_code(doc, key, forward):
    """Move the cursor to the next/previous code with this key.
    Returns (found_text_or_None, wrapped)."""
    scan = scan_document(doc)
    view = doc.CurrentController.getViewCursor()
    here = view.getStart()
    hits = []                       # (paragraph index, tok, relation to the cursor: -1 before, 0, 1 after)
    cur_idx = None
    for pi, (para, toks) in enumerate(scan):
        if cur_idx is None and _in_para(para, here):
            cur_idx = pi
    for pi, (para, toks) in enumerate(scan):
        for t in toks:
            if t.key != key or t.pos is None:
                continue
            if cur_idx is None or pi != cur_idx:
                rel = 1 if (cur_idx is not None and pi > cur_idx) else -1
                if cur_idx is None:
                    rel = 1
            else:
                try:
                    rel = 1 if para.getText().compareRegionStarts(here, _tok_range(t)) == 1 else -1
                    if para.getText().compareRegionStarts(here, _tok_range(t)) == 0:
                        rel = 0
                except Exception:
                    rel = 1
            hits.append((pi, t, rel))
    if forward:
        after = [h for h in hits if h[2] == 1]
        pick, wrapped = (after[0], False) if after else (None, True)
        if pick is None:
            pick = next((h for h in hits if h[2] != 1), None)
            if pick is not None and pick[2] == 0 and len(hits) == 1:
                return None, True
    else:
        before = [h for h in hits if h[2] == -1]
        pick, wrapped = (before[-1], False) if before else (None, True)
        if pick is None:
            pick = next((h for h in reversed(hits) if h[2] != -1), None)
            if pick is not None and pick[2] == 0 and len(hits) == 1:
                return None, True
    if pick is None:
        return None, False
    move_cursor_to(doc, pick[1].pos)
    return pick[1].text, wrapped


def collect_like(doc, key):
    """Unique deletable actions for every code like this one, in document order."""
    fam = family(key)
    actions, seen = [], set()
    for para, toks in scan_document(doc):
        for t in toks:
            if t.action is not None and family(t.key) == fam and id(t.action) not in seen:
                seen.add(id(t.action))
                actions.append(t.action)
    return actions


def delete_all_like(doc, actions):
    """Delete the codes last-to-first inside one undo step. Returns (count, first_error)."""
    undo = None
    done, err = 0, None
    try:
        undo = doc.getUndoManager()
        undo.enterUndoContext(L.t("undo_title"))
    except Exception:
        undo = None
    try:
        for action in reversed(actions):
            e = apply_action(action)
            if e is None:
                done += 1
            elif err is None:
                err = e
    finally:
        if undo is not None:
            try:
                undo.leaveUndoContext()
            except Exception as exc:
                _log("leaveUndoContext failed: %s" % exc)
    return done, err


# =====================================================================
#  The drawn panel
# =====================================================================

BG = 0xFFFFFF
TEXT = 0x202020
BOX_FILL, BOX_LINE = 0xE3ECF8, 0x4F74A8
HRT_FILL, HRT_LINE = 0xFCE8D5, 0xC27C3A
SEL_FILL, SEL_LINE = 0x2E6BD0, 0x123C80
CURSOR = 0xD02020
HINT = 0x707070
MARGIN, PAD, GAP = 6, 4, 4


class CodesWindow(unohelper.Base, XPaintListener, XMouseListener, XKeyListener,
                  XWindowListener):
    def __init__(self, ctx, doc, parent):
        self.ctx = ctx
        self.doc = doc
        self.tokens = [Tok("text", L.t("loading"))]
        self.selected = None            # index into self.tokens
        self.items = []                 # drawn items: (tok, index, x, y, w, h)
        self.buttons = []               # (id, label, x, y, w, h, enabled)
        self.pending_confirm = None
        self.alive = True
        self.status = ""
        self.lock = threading.RLock()
        self._widths = {}

        smgr = ctx.getServiceManager()
        toolkit = smgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
        wd = WindowDescriptor()
        wd.Type = uno.Enum("com.sun.star.awt.WindowClass", "SIMPLE")
        wd.WindowServiceName = "window"
        wd.ParentIndex = -1
        wd.Parent = parent
        wd.Bounds = Rectangle(0, 0, 300, 300)
        wd.WindowAttributes = 1                       # SHOW
        self.peer = toolkit.createWindow(wd)
        self.window = self.peer
        self.window.addPaintListener(self)
        self.window.addMouseListener(self)
        self.window.addKeyListener(self)
        self.window.addWindowListener(self)

        self.fd = FontDescriptor()
        self.fd.Name = "Menlo;DejaVu Sans Mono;Liberation Mono;Courier New"
        self.fd.Height = 12
        self.fd.Width = 0
        self.fd.Weight = 100

    # ---- data from the polling thread ----
    def set_tokens(self, toks):
        with self.lock:
            self.tokens = toks
            self.selected = None
        self.repaint()

    def repaint(self):
        try:
            self.peer.invalidate(0)
        except Exception:
            pass

    # ---- measuring and layout ----
    def _setup(self, gfx):
        dev = gfx.getDevice()
        self.font = dev.getFont(self.fd)
        gfx.setFont(self.font)
        try:
            m = self.font.getFontMetric()
            self.lh = int(m.Ascent + m.Descent) + 2 * PAD + 3
        except Exception:
            self.lh = 12 + 2 * PAD + 5
        self.text_h = self.lh - 2 * PAD - 3

    def _tw(self, s):
        w = self._widths.get(s)
        if w is None:
            w = self.font.getStringWidth(s)
            self._widths[s] = w
        return w

    def _bar_height(self, width):
        specs = [("a", L.t("b_delete"), 1), ("b", L.t("b_delall"), 1),
                 ("c", u"\u25C0 " + L.t("b_prev"), 1), ("d", L.t("b_next") + u" \u25B6", 1)]
        return self._bar_layout(width, specs)[1]

    def _layout(self, width):
        items = []
        x, y = MARGIN, MARGIN
        for i, t in enumerate(self.tokens):
            if t.kind == "gap":
                if x > MARGIN:
                    x, y = MARGIN, y + self.lh
                y += self.lh // 2
                continue
            if t.kind == "cursor":
                w = 4
            elif t.kind in ("code", "hrt"):
                w = self._tw(t.text) + 2 * PAD
            else:
                w = self._tw(t.text)
            if x + w > width - MARGIN and x > MARGIN and t.kind != "cursor":
                x, y = MARGIN, y + self.lh
            items.append((t, i, x, y, w, self.lh - 2))
            x += w + (GAP if t.kind in ("code", "hrt") else 0)
            if t.kind == "hrt":
                x, y = MARGIN, y + self.lh
        return items, y + self.lh

    # ---- painting ----
    def windowPaint(self, ev):
        try:
            self._paint()
        except Exception as exc:
            _log("paint failed: %s\n%s" % (exc, traceback.format_exc()))

    def _paint(self):
        r = self.window.getPosSize()
        width, height = r.Width, r.Height
        gfx = self.peer.createGraphics()
        self._setup(gfx)
        bar_h = self._bar_height(width)
        with self.lock:
            items, total = self._layout(width)
            self.items = items
            sel = self.selected

            # scroll so the cursor line stays visible
            view_h = height - bar_h
            scroll = 0
            if total > view_h:
                for t, i, x, y, w, h in items:
                    if t.kind == "cursor":
                        scroll = y - view_h // 2
                scroll = max(0, min(scroll, total - view_h))
            self.scroll = scroll

            gfx.setFillColor(BG)
            gfx.setLineColor(BG)
            gfx.drawRect(0, 0, width, height)

            for t, i, x, y, w, h in items:
                yy = y - scroll
                if yy + h < 0 or yy > view_h:
                    continue
                if t.kind == "cursor":
                    gfx.setFillColor(CURSOR)
                    gfx.setLineColor(CURSOR)
                    gfx.drawRect(x, yy, w - 1, h)
                elif t.kind in ("code", "hrt"):
                    if i == sel:
                        fill, line, fg = SEL_FILL, SEL_LINE, 0xFFFFFF
                    elif t.kind == "hrt":
                        fill, line, fg = HRT_FILL, HRT_LINE, TEXT
                    else:
                        fill, line, fg = BOX_FILL, BOX_LINE, TEXT
                    gfx.setFillColor(fill)
                    gfx.setLineColor(line)
                    gfx.drawRoundedRect(x, yy, w, h, 4, 4)
                    gfx.setTextColor(fg)
                    gfx.drawText(x + PAD, yy + PAD, t.text)
                else:
                    gfx.setTextColor(TEXT)
                    gfx.drawText(x, yy + PAD, t.text)

            # bottom bar: Delete / Delete all / Find buttons, then a status line
            tok = self.tokens[sel] if sel is not None and sel < len(self.tokens) else None
            has_key = tok is not None and tok.key is not None
            can_del = tok is not None and tok.action is not None
            can_all = can_del and family(tok.key) != "HRt"
            specs = [("del", L.t("b_delete"), can_del),
                     ("delall", L.t("b_delall"), can_all),
                     ("prev", u"\u25C0 " + L.t("b_prev"), has_key),
                     ("next", L.t("b_next") + u" \u25B6", has_key)]
            rects, bar_h = self._bar_layout(width, specs)
            by = height - bar_h
            gfx.setFillColor(0xF2F2F2)
            gfx.setLineColor(0xD0D0D0)
            gfx.drawRect(0, by, width, bar_h)
            self.buttons = []
            for (bid, label, enabled), (bx, byy, bw, bh) in zip(specs, rects):
                gfx.setFillColor(0xFFFFFF if enabled else 0xE6E6E6)
                gfx.setLineColor(0x4F74A8 if enabled else 0xB0B0B0)
                gfx.drawRoundedRect(bx, by + byy, bw, bh, 4, 4)
                gfx.setTextColor(TEXT if enabled else HINT)
                gfx.drawText(bx + PAD + 4, by + byy + PAD, label)
                self.buttons.append((bid, bx, by + byy, bw, bh, enabled))
            hint = self.status or (L.t("hint") if sel is None else self.tokens[sel].text)
            gfx.setTextColor(HINT)
            gfx.drawText(MARGIN, by + bar_h - self.lh, hint)

    def _bar_layout(self, width, specs):
        """Wrap the buttons into rows. Returns (rects relative to the bar, bar height)."""
        rects = []
        x, y = MARGIN, 4
        for bid, label, enabled in specs:
            bw = self._tw(label) + 2 * PAD + 8
            if x + bw > width - MARGIN and x > MARGIN:
                x, y = MARGIN, y + self.lh + 4
            rects.append((x, y, bw, self.lh))
            x += bw + 6
        return rects, y + self.lh + 4 + self.lh + 4

    # ---- mouse and keys ----
    def mousePressed(self, ev):
        try:
            self._click(ev.X, ev.Y)
        except Exception as exc:
            _log("click failed: %s\n%s" % (exc, traceback.format_exc()))

    def mouseReleased(self, ev):
        pass

    def _click(self, mx, my):
        try:
            self.window.setFocus()
        except Exception:
            pass
        self.status = ""
        for bid, bx, by, bw, bh, enabled in self.buttons:
            if bx <= mx <= bx + bw and by <= my <= by + bh:
                if enabled:
                    self._button(bid)
                self.repaint()
                return
        hit = None
        with self.lock:
            for t, i, x, y, w, h in self.items:
                yy = y - getattr(self, "scroll", 0)
                if x <= mx <= x + w and yy <= my <= yy + h and t.kind != "cursor":
                    hit = (t, i)
                    break
        if hit is None:
            self.selected = None
        elif hit[0].kind in ("code", "hrt"):
            self.selected = hit[1]
        else:
            self.selected = None
            if hit[0].pos is not None:
                move_cursor_to(self.doc, hit[0].pos)
                self._refocus_document()
        self.repaint()

    def _refocus_document(self):
        try:
            self.doc.CurrentController.Frame.getComponentWindow().setFocus()
        except Exception:
            pass

    def _selected_tok(self):
        with self.lock:
            idx = self.selected
            return self.tokens[idx] if idx is not None and idx < len(self.tokens) else None

    def _button(self, bid):
        try:
            if bid == "del":
                self.delete_selected()
            elif bid == "delall":
                self.delete_all_selected()
            else:
                self.find_selected(bid == "next")
        except Exception as exc:
            _log("button %s failed: %s\n%s" % (bid, exc, traceback.format_exc()))
            self.status = L.t("err_delete") % exc

    def delete_selected(self):
        tok = self._selected_tok()
        if tok is None or tok.action is None:
            self.status = L.t("nothing")
            self.repaint()
            return
        err = apply_action(tok.action)
        self.status = (L.t("err_delete") % err) if err else ""
        self.selected = None
        self.force_refresh = True
        self.repaint()

    def find_selected(self, forward):
        tok = self._selected_tok()
        if tok is None or tok.key is None:
            return
        key, label = tok.key, tok.text
        self.status = L.t("searching")
        found, wrapped = find_code(self.doc, key, forward)
        if found is None:
            self.status = L.t("nomatch") % label
        else:
            self.status = L.t("wrapped") if wrapped else ""
            self._refocus_document()
        self.force_refresh = True

    def _confirm(self, message):
        """Yes/No box. Returns True/False, or None if no box could be shown."""
        try:
            toolkit = self.ctx.getServiceManager().createInstanceWithContext(
                "com.sun.star.awt.Toolkit", self.ctx)
            from com.sun.star.awt.MessageBoxType import QUERYBOX
            from com.sun.star.awt.MessageBoxButtons import BUTTONS_YES_NO, DEFAULT_BUTTON_NO
            box = toolkit.createMessageBox(self.peer, QUERYBOX, BUTTONS_YES_NO + DEFAULT_BUTTON_NO,
                                           "Reveal Codes", message)
            result = box.execute()
            try:
                box.dispose()
            except Exception:
                pass
            return result == 2          # MessageBoxResults.YES
        except Exception as exc:
            _log("confirm box failed: %s" % exc)
            return None

    def delete_all_selected(self):
        tok = self._selected_tok()
        if tok is None or tok.action is None or family(tok.key) == "HRt":
            self.status = L.t("no_hrt_all") if tok is not None and tok.key == "HRt" else L.t("nothing")
            return
        key, label = tok.key, tok.text
        self.status = L.t("searching")
        actions = collect_like(self.doc, key)
        if not actions:
            self.status = L.t("nothing")
            return
        msg = L.t("confirm") % {"n": len(actions), "c": label}
        answer = self._confirm(msg)
        if answer is None:                      # no dialog available: ask for a second click
            if self.pending_confirm != key:
                self.pending_confirm = key
                self.status = L.t("confirm").split("\n")[0] % {"n": len(actions), "c": label}
                return
        self.pending_confirm = None
        if answer is False:
            self.status = ""
            return
        done, err = delete_all_like(self.doc, actions)
        self.status = (L.t("err_delete") % err) if err and not done else (L.t("deleted") % done)
        self.selected = None
        self.force_refresh = True

    def mouseEntered(self, ev):
        pass

    def mouseExited(self, ev):
        pass

    def keyPressed(self, ev):
        pass

    def keyReleased(self, ev):
        try:
            delete = uno.getConstantByName("com.sun.star.awt.Key.DELETE")
            back = uno.getConstantByName("com.sun.star.awt.Key.BACKSPACE")
            if ev.KeyCode in (delete, back):
                self.delete_selected()
        except Exception as exc:
            _log("key failed: %s" % exc)

    # ---- window events ----
    def windowResized(self, ev):
        self.repaint()

    def windowMoved(self, ev):
        pass

    def windowShown(self, ev):
        self.repaint()

    def windowHidden(self, ev):
        pass

    def disposing(self, ev):
        self.alive = False


# =====================================================================
#  Sidebar plumbing
# =====================================================================

class RevealCodesPanel(unohelper.Base, XSidebarPanel, XUIElement, XToolPanel):
    def __init__(self, ctx, frame, parent, resource_url):
        self.ctx = ctx
        self.frame = frame
        self.resource_url = resource_url
        self.alive = True
        self.cw = None
        self.doc = None
        try:
            self.doc = frame.getController().getModel()
        except Exception:
            pass
        try:
            L.init(ctx)
        except Exception as exc:
            _log("language init failed: %s" % exc)
        self.cw = CodesWindow(ctx, self.doc, parent)
        self.cw.force_refresh = False
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def _poll(self):
        last = None
        tick = 0
        while self.alive and self.cw is not None and self.cw.alive:
            try:
                tick += 1
                if tick % 8 == 0 and L.init(self.ctx):
                    self.cw._widths.clear()
                    self.cw.force_refresh = True
                if not self.doc.supportsService("com.sun.star.text.TextDocument"):
                    toks = [Tok("text", L.t("only_writer"))]
                else:
                    toks = build_tokens(self.doc)
                sig = signature(toks)
                if sig != last or self.cw.force_refresh:
                    last = sig
                    self.cw.force_refresh = False
                    self.cw.set_tokens(toks)
            except Exception as exc:
                name = type(exc).__name__
                if "Disposed" in name or "disposed" in str(exc):
                    break
                _log("poll error: %s\n%s" % (exc, traceback.format_exc()))
            time.sleep(0.25)

    # XUIElement
    def getRealInterface(self):
        return self

    def update(self):
        pass

    def getFrame(self):
        return self.frame

    def getResourceURL(self):
        return self.resource_url

    def getType(self):
        return 3    # UIElementType.TOOLPANEL

    Frame = property(getFrame)
    ResourceURL = property(getResourceURL)
    Type = property(getType)

    # XToolPanel
    def getWindow(self):
        return self.cw.window

    def createAccessible(self, parent):
        return None

    Window = property(getWindow)

    # XSidebarPanel
    def getHeightRequest(self, width):
        return LayoutSize(100, -1, 400)

    def getHeightForWidth(self, width):
        return LayoutSize(100, -1, 400)

    def getMinimalWidth(self):
        return 120

    # XComponent
    def dispose(self):
        self.alive = False
        try:
            if self.cw is not None:
                self.cw.alive = False
                self.cw.window.dispose()
        except Exception:
            pass

    def addEventListener(self, listener):
        pass

    def removeEventListener(self, listener):
        pass


class PanelFactory(unohelper.Base, XUIElementFactory):
    def __init__(self, ctx):
        self.ctx = ctx

    def createUIElement(self, url, args):
        parent = frame = None
        for arg in args:
            if arg.Name == "ParentWindow":
                parent = arg.Value
            elif arg.Name == "Frame":
                frame = arg.Value
        try:
            return RevealCodesPanel(self.ctx, frame, parent, url)
        except Exception as exc:
            _log("createUIElement failed: %s\n%s" % (exc, traceback.format_exc()))
            raise


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(
    PanelFactory, IMPL_NAME, ("com.sun.star.ui.UIElementFactory",))
