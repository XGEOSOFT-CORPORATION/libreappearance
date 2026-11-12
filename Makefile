# Aura for LibreOffice >= 24.2
PYTHON     ?= python3
UNO_PYTHON ?= /usr/bin/python3
LO_CONFIG  ?= /usr/lib/libreoffice/share/config
INTER_DIR  ?= /usr/share/fonts/opentype/inter
STAGE      := build/oxt

.PHONY: all assets icons registry templates samples gtk ribbon oxt install uninstall clean test

all: oxt

icons:
	$(PYTHON) tools/build_icons.py --lo-config $(LO_CONFIG) --out $(STAGE)/iconsets

registry:
	$(PYTHON) tools/build_registry.py --out $(STAGE)/registry/ColorSchemes.xcu

templates:
	$(UNO_PYTHON) tools/build_templates.py --out $(STAGE)/templates/Aura

samples:
	$(UNO_PYTHON) tools/build_templates.py --out $(STAGE)/templates/Aura --samples build/samples

gtk:
	$(PYTHON) tools/build_gtk.py --out $(STAGE)/gtk

ribbon:
	$(PYTHON) tools/build_ribbon.py --out $(STAGE)/ui

assets: icons registry samples gtk ribbon

oxt: assets
	$(PYTHON) tools/build_oxt.py --fonts $(INTER_DIR)

install: oxt
	unopkg add --force dist/Aura-*.oxt

uninstall:
	unopkg remove org.libreappearance.aura

clean:
	rm -rf build dist

test: oxt
	$(PYTHON) tools/test_table_html.py
	$(UNO_PYTHON) tools/test_extension.py
	$(UNO_PYTHON) tools/test_commands.py
