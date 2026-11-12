"""The Aura panel (Extensions tab ▸ Aura ▸ Aura panel, or Tools ▸ Aura ▸ Aura panel)
and the first-run welcome.

One window, a section list on the left and the section's settings on the
right; Apply writes the preferences and applies them, Restart restarts
LibreOffice so everything shows. Built in code (no dialog file) so it follows
the UI language and LibreOffice's own look on every platform.
"""
import sys
import traceback

import uno
import unohelper
from com.sun.star.awt import XActionListener, XItemListener

T = {
    "fr": {
        "d_engine_on": "Moteur : installé, hors ligne ({m})",
        "d_engine_off": "Moteur : non installé (hors ligne, gratuit)",
        "d_language": "Langue",
        "d_auto": "Détection automatique (7 langues)",
        "d_model": "Précision",
        "d_models": ["Automatique (recommandé)", "Rapide — small, 0,5 Go", "Très précis — large-v3-turbo, 1,6 Go", "Maximal — large-v3, 3 Go", "Léger — base, 0,15 Go"],
        "d_device": "Calcul",
        "d_devices": ["Automatique", "Processeur", "Carte graphique NVIDIA"],
        "d_yoruba": "Yoruba",
        "d_yorubas": ["Whisper", "Meta MMS (plus précis, +3 Go)"],
        "d_chinese": "Chinois",
        "d_chineses": ["Simplifié", "Traditionnel"],
        "d_glossary": "Vocabulaire",
        "d_commands": "Commandes vocales : « nouveau paragraphe », « virgule », « efface ça »…",
        "d_shortcut": "Raccourci Ctrl+Alt+Espace",
        "d_install": "Installer le moteur",
        "d_update": "Mettre à jour",
        "d_start": "Démarrer la dictée",
        "d_remove": "Supprimer",
        "title": "Aura — Panneau", "sections": ["Apparence", "Ruban", "Documents", "Tableaux", "Performance", "Dictée vocale", "À propos"],
        "theme": "Thème", "light": "Clair", "dark": "Sombre",
        "icons": "Icônes", "icons_auto": "Selon le thème (recommandé)", "icons_aura": "Aura claires",
        "icons_aura_dark": "Aura sombres", "icons_original": "Celles de LibreOffice",
        "layout": "Disposition", "layout_compact": "Onglets compacts (recommandé)", "layout_tabbed": "Onglets",
        "layout_single": "Barre d'outils unique", "layout_default": "Barres d'outils classiques",
        "gtk": "Habiller les fenêtres de LibreOffice (thème GTK Aura, Linux)",
        "ribbon_intro": "Les onglets trop chargés sont répartis par thème pour que chaque outil reste visible.",
        "extensions_tab": "Organiser l'onglet Extensions : un groupe par extension installée",
        "extensions_found": "Extensions détectées : {n}",
        "refresh": "Actualiser le ruban maintenant",
        "templates": "Créer les nouveaux documents à partir des modèles Aura",
        "templates_open": "Ouvrir les modèles…",
        "font_ok": "Police Inter : installée", "font_missing": "Police Inter : sera installée à l'application",
        "smart_paste": "Ctrl+V dans Writer garde la mise en forme des tableaux (Calc, Excel, web)",
        "paste_help": "Dans Impress et Draw : Extensions ▸ Aura ▸ Coller le tableau. Le texte et le contenu "
                      "Writer se collent normalement.",
        "tips": "Afficher l'astuce du jour au démarrage",
        "cache": "Mémoire pour les images",
        "cache_values": ["300 Mo (LibreOffice)", "600 Mo (recommandé)", "1 Go (documents très illustrés)"],
        "version": "Version d'Aura : {v}", "office": "LibreOffice : {v}", "language": "Langue de l'interface : {v}",
        "status_on": "État : Aura est appliqué", "status_off": "État : Aura n'est pas appliqué",
        "restore": "Restaurer l'apparence d'origine", "uninstall": "Désinstaller Aura proprement…",
        "apply": "Appliquer", "close": "Fermer", "restart": "Redémarrer LibreOffice",
        "applied": "Appliqué. Redémarrez LibreOffice pour tout voir.", "restored": "Apparence d'origine restaurée.",
        "refreshed": "Ruban actualisé.", "uninstall_confirm": "Restaurer l'apparence d'origine puis retirer "
        "l'extension Aura ? LibreOffice redémarrera.",
        "welcome_title": "Bienvenue dans Aura",
        "welcome": "Aura donne à LibreOffice une interface moderne et épurée : nouvelles icônes, ruban organisé "
                   "par thème, modèles Premium, collage fidèle des tableaux.\n\nVous pourrez tout régler ou revenir "
                   "en arrière à tout moment : Outils ▸ Aura ▸ Panneau Aura.",
        "welcome_light": "Appliquer Aura clair", "welcome_dark": "Appliquer Aura sombre", "later": "Plus tard",
    },
    "en": {
        "d_engine_on": "Engine: installed, offline ({m})",
        "d_engine_off": "Engine: not installed (offline, free)",
        "d_language": "Language",
        "d_auto": "Automatic detection (7 languages)",
        "d_model": "Accuracy",
        "d_models": ["Automatic (recommended)", "Fast — small, 0.5 GB", "Very accurate — large-v3-turbo, 1.6 GB", "Maximum — large-v3, 3 GB", "Light — base, 0.15 GB"],
        "d_device": "Compute",
        "d_devices": ["Automatic", "Processor", "NVIDIA graphics card"],
        "d_yoruba": "Yoruba",
        "d_yorubas": ["Whisper", "Meta MMS (more accurate, +3 GB)"],
        "d_chinese": "Chinese",
        "d_chineses": ["Simplified", "Traditional"],
        "d_glossary": "Vocabulary",
        "d_commands": "Voice commands: “new paragraph”, “comma”, “delete that”…",
        "d_shortcut": "Ctrl+Alt+Space shortcut",
        "d_install": "Install the engine",
        "d_update": "Update",
        "d_start": "Start dictation",
        "d_remove": "Remove",
        "title": "Aura — Panel", "sections": ["Appearance", "Ribbon", "Documents", "Tables", "Performance", "Dictation", "About"],
        "theme": "Theme", "light": "Light", "dark": "Dark",
        "icons": "Icons", "icons_auto": "Follow the theme (recommended)", "icons_aura": "Aura light",
        "icons_aura_dark": "Aura dark", "icons_original": "LibreOffice's own",
        "layout": "Layout", "layout_compact": "Tabbed compact (recommended)", "layout_tabbed": "Tabbed",
        "layout_single": "Single toolbar", "layout_default": "Classic toolbars",
        "gtk": "Style LibreOffice's windows (Aura GTK theme, Linux)",
        "ribbon_intro": "Crowded tabs are split by theme so every tool stays visible.",
        "extensions_tab": "Organise the Extensions tab: one group per installed extension",
        "extensions_found": "Extensions found: {n}",
        "refresh": "Refresh the ribbon now",
        "templates": "Start new documents from the Aura templates",
        "templates_open": "Open templates…",
        "font_ok": "Inter font: installed", "font_missing": "Inter font: installed when you apply",
        "smart_paste": "Ctrl+V in Writer keeps table formatting (Calc, Excel, web)",
        "paste_help": "In Impress and Draw: Extensions ▸ Aura ▸ Paste table. Text and Writer content paste "
                      "as usual.",
        "tips": "Show the Tip of the Day at start-up",
        "cache": "Memory for images",
        "cache_values": ["300 MB (LibreOffice)", "600 MB (recommended)", "1 GB (image-heavy documents)"],
        "version": "Aura version: {v}", "office": "LibreOffice: {v}", "language": "UI language: {v}",
        "status_on": "Status: Aura is applied", "status_off": "Status: Aura is not applied",
        "restore": "Restore original appearance", "uninstall": "Uninstall Aura cleanly…",
        "apply": "Apply", "close": "Close", "restart": "Restart LibreOffice",
        "applied": "Applied. Restart LibreOffice to see everything.", "restored": "Original appearance restored.",
        "refreshed": "Ribbon refreshed.", "uninstall_confirm": "Restore the original appearance, then remove "
        "the Aura extension? LibreOffice will restart.",
        "welcome_title": "Welcome to Aura",
        "welcome": "Aura gives LibreOffice a modern, clean interface: new icons, a ribbon organised by theme, "
                   "Premium templates, faithful table paste.\n\nYou can adjust or undo everything at any time: "
                   "Tools ▸ Aura ▸ Aura panel.",
        "welcome_light": "Apply Aura light", "welcome_dark": "Apply Aura dark", "later": "Later",
    },
    "de": {
        "d_engine_on": "Engine: installiert, offline ({m})",
        "d_engine_off": "Engine: nicht installiert (offline, kostenlos)",
        "d_language": "Sprache",
        "d_auto": "Automatische Erkennung (7 Sprachen)",
        "d_model": "Genauigkeit",
        "d_models": ["Automatisch (empfohlen)", "Schnell — small, 0,5 GB", "Sehr genau — large-v3-turbo, 1,6 GB", "Maximal — large-v3, 3 GB", "Leicht — base, 0,15 GB"],
        "d_device": "Berechnung",
        "d_devices": ["Automatisch", "Prozessor", "NVIDIA-Grafikkarte"],
        "d_yoruba": "Yoruba",
        "d_yorubas": ["Whisper", "Meta MMS (genauer, +3 GB)"],
        "d_chinese": "Chinesisch",
        "d_chineses": ["Vereinfacht", "Traditionell"],
        "d_glossary": "Vokabular",
        "d_commands": "Sprachbefehle: „new paragraph“, „comma“, „delete that“…",
        "d_shortcut": "Tastenkürzel Strg+Alt+Leertaste",
        "d_install": "Engine installieren",
        "d_update": "Aktualisieren",
        "d_start": "Diktat starten",
        "d_remove": "Entfernen",
        "title": "Aura — Bedienfeld", "sections": ["Erscheinungsbild", "Menüband", "Dokumente", "Tabellen", "Leistung", "Diktat", "Info"],
        "theme": "Design", "light": "Hell", "dark": "Dunkel",
        "icons": "Symbole", "icons_auto": "Wie das Design (empfohlen)", "icons_aura": "Aura hell",
        "icons_aura_dark": "Aura dunkel", "icons_original": "Die von LibreOffice",
        "layout": "Anordnung", "layout_compact": "Kompakte Register (empfohlen)", "layout_tabbed": "Register",
        "layout_single": "Einzelne Symbolleiste", "layout_default": "Klassische Symbolleisten",
        "gtk": "LibreOffice-Fenster gestalten (Aura-GTK-Design, Linux)",
        "ribbon_intro": "Überfüllte Register werden nach Thema aufgeteilt, damit jedes Werkzeug sichtbar bleibt.",
        "extensions_tab": "Register Erweiterungen ordnen: eine Gruppe pro Erweiterung",
        "extensions_found": "Gefundene Erweiterungen: {n}",
        "refresh": "Menüband jetzt aktualisieren",
        "templates": "Neue Dokumente aus den Aura-Vorlagen erstellen",
        "templates_open": "Vorlagen öffnen…",
        "font_ok": "Schrift Inter: installiert", "font_missing": "Schrift Inter: wird beim Anwenden installiert",
        "smart_paste": "Strg+V in Writer behält die Tabellenformatierung (Calc, Excel, Web)",
        "paste_help": "In Impress und Draw: Erweiterungen ▸ Aura ▸ Tabelle einfügen. Text und Writer-Inhalte "
                      "werden normal eingefügt.",
        "tips": "Tipp des Tages beim Start anzeigen",
        "cache": "Speicher für Bilder",
        "cache_values": ["300 MB (LibreOffice)", "600 MB (empfohlen)", "1 GB (bildreiche Dokumente)"],
        "version": "Aura-Version: {v}", "office": "LibreOffice: {v}", "language": "Sprache der Oberfläche: {v}",
        "status_on": "Status: Aura ist angewendet", "status_off": "Status: Aura ist nicht angewendet",
        "restore": "Ursprüngliches Erscheinungsbild", "uninstall": "Aura sauber deinstallieren…",
        "apply": "Anwenden", "close": "Schließen", "restart": "LibreOffice neu starten",
        "applied": "Angewendet. Starten Sie LibreOffice neu, um alles zu sehen.",
        "restored": "Ursprüngliches Erscheinungsbild wiederhergestellt.", "refreshed": "Menüband aktualisiert.",
        "uninstall_confirm": "Ursprüngliches Erscheinungsbild wiederherstellen und Aura entfernen? "
        "LibreOffice wird neu gestartet.",
        "welcome_title": "Willkommen bei Aura",
        "welcome": "Aura gibt LibreOffice eine moderne, aufgeräumte Oberfläche: neue Symbole, ein nach Themen "
                   "geordnetes Menüband, Premium-Vorlagen, originalgetreues Einfügen von Tabellen.\n\nAlles "
                   "lässt sich jederzeit anpassen oder rückgängig machen: Extras ▸ Aura ▸ Aura-Bedienfeld.",
        "welcome_light": "Aura hell anwenden", "welcome_dark": "Aura dunkel anwenden", "later": "Später",
    },
    "es": {
        "d_engine_on": "Motor: instalado, sin conexión ({m})",
        "d_engine_off": "Motor: no instalado (sin conexión, gratuito)",
        "d_language": "Idioma",
        "d_auto": "Detección automática (7 idiomas)",
        "d_model": "Precisión",
        "d_models": ["Automático (recomendado)", "Rápido — small, 0,5 GB", "Muy preciso — large-v3-turbo, 1,6 GB", "Máximo — large-v3, 3 GB", "Ligero — base, 0,15 GB"],
        "d_device": "Cálculo",
        "d_devices": ["Automático", "Procesador", "Tarjeta gráfica NVIDIA"],
        "d_yoruba": "Yoruba",
        "d_yorubas": ["Whisper", "Meta MMS (más preciso, +3 GB)"],
        "d_chinese": "Chino",
        "d_chineses": ["Simplificado", "Tradicional"],
        "d_glossary": "Vocabulario",
        "d_commands": "Comandos de voz: «nuevo párrafo», «coma», «borrar eso»…",
        "d_shortcut": "Atajo Ctrl+Alt+Espacio",
        "d_install": "Instalar el motor",
        "d_update": "Actualizar",
        "d_start": "Iniciar dictado",
        "d_remove": "Eliminar",
        "title": "Aura — Panel", "sections": ["Apariencia", "Cinta", "Documentos", "Tablas", "Rendimiento", "Dictado", "Acerca de"],
        "theme": "Tema", "light": "Claro", "dark": "Oscuro",
        "icons": "Iconos", "icons_auto": "Según el tema (recomendado)", "icons_aura": "Aura claros",
        "icons_aura_dark": "Aura oscuros", "icons_original": "Los de LibreOffice",
        "layout": "Disposición", "layout_compact": "Pestañas compactas (recomendado)", "layout_tabbed": "Pestañas",
        "layout_single": "Barra de herramientas única", "layout_default": "Barras de herramientas clásicas",
        "gtk": "Dar estilo a las ventanas de LibreOffice (tema GTK Aura, Linux)",
        "ribbon_intro": "Las pestañas sobrecargadas se dividen por tema para que cada herramienta quede visible.",
        "extensions_tab": "Organizar la pestaña Extensiones: un grupo por extensión",
        "extensions_found": "Extensiones detectadas: {n}",
        "refresh": "Actualizar la cinta ahora",
        "templates": "Crear los documentos nuevos a partir de las plantillas Aura",
        "templates_open": "Abrir plantillas…",
        "font_ok": "Fuente Inter: instalada", "font_missing": "Fuente Inter: se instalará al aplicar",
        "smart_paste": "Ctrl+V en Writer conserva el formato de las tablas (Calc, Excel, web)",
        "paste_help": "En Impress y Draw: Extensiones ▸ Aura ▸ Pegar tabla. El texto y el contenido de Writer "
                      "se pegan como siempre.",
        "tips": "Mostrar el consejo del día al iniciar",
        "cache": "Memoria para imágenes",
        "cache_values": ["300 MB (LibreOffice)", "600 MB (recomendado)", "1 GB (documentos con muchas imágenes)"],
        "version": "Versión de Aura: {v}", "office": "LibreOffice: {v}", "language": "Idioma de la interfaz: {v}",
        "status_on": "Estado: Aura está aplicado", "status_off": "Estado: Aura no está aplicado",
        "restore": "Restaurar la apariencia original", "uninstall": "Desinstalar Aura limpiamente…",
        "apply": "Aplicar", "close": "Cerrar", "restart": "Reiniciar LibreOffice",
        "applied": "Aplicado. Reinicie LibreOffice para verlo todo.", "restored": "Apariencia original restaurada.",
        "refreshed": "Cinta actualizada.", "uninstall_confirm": "¿Restaurar la apariencia original y quitar "
        "Aura? LibreOffice se reiniciará.",
        "welcome_title": "Bienvenido a Aura",
        "welcome": "Aura da a LibreOffice una interfaz moderna y limpia: iconos nuevos, una cinta organizada por "
                   "temas, plantillas Premium, pegado fiel de tablas.\n\nPuede ajustarlo o deshacerlo todo en "
                   "cualquier momento: Herramientas ▸ Aura ▸ Panel de Aura.",
        "welcome_light": "Aplicar Aura claro", "welcome_dark": "Aplicar Aura oscuro", "later": "Más tarde",
    },
    "it": {
        "d_engine_on": "Motore: installato, offline ({m})",
        "d_engine_off": "Motore: non installato (offline, gratuito)",
        "d_language": "Lingua",
        "d_auto": "Rilevamento automatico (7 lingue)",
        "d_model": "Precisione",
        "d_models": ["Automatica (consigliata)", "Veloce — small, 0,5 GB", "Molto precisa — large-v3-turbo, 1,6 GB", "Massima — large-v3, 3 GB", "Leggera — base, 0,15 GB"],
        "d_device": "Calcolo",
        "d_devices": ["Automatico", "Processore", "Scheda grafica NVIDIA"],
        "d_yoruba": "Yoruba",
        "d_yorubas": ["Whisper", "Meta MMS (più preciso, +3 GB)"],
        "d_chinese": "Cinese",
        "d_chineses": ["Semplificato", "Tradizionale"],
        "d_glossary": "Vocabolario",
        "d_commands": "Comandi vocali: «new paragraph», «comma», «delete that»…",
        "d_shortcut": "Scorciatoia Ctrl+Alt+Spazio",
        "d_install": "Installa il motore",
        "d_update": "Aggiorna",
        "d_start": "Avvia dettatura",
        "d_remove": "Rimuovi",
        "title": "Aura — Pannello", "sections": ["Aspetto", "Barra", "Documenti", "Tabelle", "Prestazioni", "Dettatura", "Informazioni"],
        "theme": "Tema", "light": "Chiaro", "dark": "Scuro",
        "icons": "Icone", "icons_auto": "Come il tema (consigliato)", "icons_aura": "Aura chiare",
        "icons_aura_dark": "Aura scure", "icons_original": "Quelle di LibreOffice",
        "layout": "Disposizione", "layout_compact": "Schede compatte (consigliato)", "layout_tabbed": "Schede",
        "layout_single": "Barra degli strumenti singola", "layout_default": "Barre degli strumenti classiche",
        "gtk": "Stile per le finestre di LibreOffice (tema GTK Aura, Linux)",
        "ribbon_intro": "Le schede troppo piene sono divise per tema perché ogni strumento resti visibile.",
        "extensions_tab": "Organizza la scheda Estensioni: un gruppo per estensione",
        "extensions_found": "Estensioni trovate: {n}",
        "refresh": "Aggiorna la barra ora",
        "templates": "Crea i nuovi documenti dai modelli Aura",
        "templates_open": "Apri modelli…",
        "font_ok": "Carattere Inter: installato", "font_missing": "Carattere Inter: installato all'applicazione",
        "smart_paste": "Ctrl+V in Writer mantiene la formattazione delle tabelle (Calc, Excel, web)",
        "paste_help": "In Impress e Draw: Estensioni ▸ Aura ▸ Incolla tabella. Testo e contenuti di Writer si "
                      "incollano come sempre.",
        "tips": "Mostra il suggerimento del giorno all'avvio",
        "cache": "Memoria per le immagini",
        "cache_values": ["300 MB (LibreOffice)", "600 MB (consigliato)", "1 GB (documenti con molte immagini)"],
        "version": "Versione di Aura: {v}", "office": "LibreOffice: {v}", "language": "Lingua dell'interfaccia: {v}",
        "status_on": "Stato: Aura è applicato", "status_off": "Stato: Aura non è applicato",
        "restore": "Ripristina l'aspetto originale", "uninstall": "Disinstalla Aura in modo pulito…",
        "apply": "Applica", "close": "Chiudi", "restart": "Riavvia LibreOffice",
        "applied": "Applicato. Riavvia LibreOffice per vedere tutto.", "restored": "Aspetto originale ripristinato.",
        "refreshed": "Barra aggiornata.", "uninstall_confirm": "Ripristinare l'aspetto originale e rimuovere "
        "Aura? LibreOffice verrà riavviato.",
        "welcome_title": "Benvenuto in Aura",
        "welcome": "Aura dà a LibreOffice un'interfaccia moderna e pulita: nuove icone, una barra organizzata per "
                   "temi, modelli Premium, incolla fedele delle tabelle.\n\nPuoi regolare o annullare tutto in "
                   "qualsiasi momento: Strumenti ▸ Aura ▸ Pannello Aura.",
        "welcome_light": "Applica Aura chiaro", "welcome_dark": "Applica Aura scuro", "later": "Più tardi",
    },
    "pt": {
        "d_engine_on": "Motor: instalado, offline ({m})",
        "d_engine_off": "Motor: não instalado (offline, gratuito)",
        "d_language": "Idioma",
        "d_auto": "Deteção automática (7 idiomas)",
        "d_model": "Precisão",
        "d_models": ["Automática (recomendada)", "Rápida — small, 0,5 GB", "Muito precisa — large-v3-turbo, 1,6 GB", "Máxima — large-v3, 3 GB", "Leve — base, 0,15 GB"],
        "d_device": "Cálculo",
        "d_devices": ["Automático", "Processador", "Placa gráfica NVIDIA"],
        "d_yoruba": "Iorubá",
        "d_yorubas": ["Whisper", "Meta MMS (mais preciso, +3 GB)"],
        "d_chinese": "Chinês",
        "d_chineses": ["Simplificado", "Tradicional"],
        "d_glossary": "Vocabulário",
        "d_commands": "Comandos de voz: «new paragraph», «comma», «delete that»…",
        "d_shortcut": "Atalho Ctrl+Alt+Espaço",
        "d_install": "Instalar o motor",
        "d_update": "Atualizar",
        "d_start": "Iniciar ditado",
        "d_remove": "Remover",
        "title": "Aura — Painel", "sections": ["Aparência", "Faixa", "Documentos", "Tabelas", "Desempenho", "Ditado", "Sobre"],
        "theme": "Tema", "light": "Claro", "dark": "Escuro",
        "icons": "Ícones", "icons_auto": "Conforme o tema (recomendado)", "icons_aura": "Aura claros",
        "icons_aura_dark": "Aura escuros", "icons_original": "Os do LibreOffice",
        "layout": "Disposição", "layout_compact": "Separadores compactos (recomendado)", "layout_tabbed": "Separadores",
        "layout_single": "Barra de ferramentas única", "layout_default": "Barras de ferramentas clássicas",
        "gtk": "Estilizar as janelas do LibreOffice (tema GTK Aura, Linux)",
        "ribbon_intro": "Os separadores sobrecarregados são divididos por tema para que cada ferramenta fique visível.",
        "extensions_tab": "Organizar o separador Extensões: um grupo por extensão",
        "extensions_found": "Extensões detetadas: {n}",
        "refresh": "Atualizar a faixa agora",
        "templates": "Criar os documentos novos a partir dos modelos Aura",
        "templates_open": "Abrir modelos…",
        "font_ok": "Tipo de letra Inter: instalado", "font_missing": "Tipo de letra Inter: instalado ao aplicar",
        "smart_paste": "Ctrl+V no Writer mantém a formatação das tabelas (Calc, Excel, web)",
        "paste_help": "No Impress e no Draw: Extensões ▸ Aura ▸ Colar tabela. O texto e o conteúdo do Writer "
                      "colam-se como habitualmente.",
        "tips": "Mostrar a dica do dia ao iniciar",
        "cache": "Memória para imagens",
        "cache_values": ["300 MB (LibreOffice)", "600 MB (recomendado)", "1 GB (documentos com muitas imagens)"],
        "version": "Versão do Aura: {v}", "office": "LibreOffice: {v}", "language": "Idioma da interface: {v}",
        "status_on": "Estado: o Aura está aplicado", "status_off": "Estado: o Aura não está aplicado",
        "restore": "Restaurar a aparência original", "uninstall": "Desinstalar o Aura de forma limpa…",
        "apply": "Aplicar", "close": "Fechar", "restart": "Reiniciar o LibreOffice",
        "applied": "Aplicado. Reinicie o LibreOffice para ver tudo.", "restored": "Aparência original restaurada.",
        "refreshed": "Faixa atualizada.", "uninstall_confirm": "Restaurar a aparência original e remover o "
        "Aura? O LibreOffice será reiniciado.",
        "welcome_title": "Bem-vindo ao Aura",
        "welcome": "O Aura dá ao LibreOffice uma interface moderna e limpa: novos ícones, uma faixa organizada "
                   "por temas, modelos Premium, colagem fiel de tabelas.\n\nPode ajustar ou anular tudo a "
                   "qualquer momento: Ferramentas ▸ Aura ▸ Painel Aura.",
        "welcome_light": "Aplicar Aura claro", "welcome_dark": "Aplicar Aura escuro", "later": "Mais tarde",
    },
}
ICON_KEYS = ("auto", "aura", "aura_dark", "original")
LAYOUT_KEYS = (("notebookbar_compact.ui", "layout_compact"), ("notebookbar.ui", "layout_tabbed"),
               ("Single", "layout_single"), ("Default", "layout_default"))
CACHES = (300000000, 600000000, 1000000000)

W, H, NAV = 330, 214, 86   # dialog size and left column width, in dialog units


class _Listener(unohelper.Base, XActionListener, XItemListener):
    """Runs a panel action; an error is shown to the user, never swallowed."""

    def __init__(self, callback, report=None):
        self.callback = callback
        self.report = report

    def _run(self, event):
        try:
            self.callback(event)
        except Exception as e:
            traceback.print_exc()
            if self.report:
                self.report(e)

    def actionPerformed(self, event):
        self._run(event)

    def itemStateChanged(self, event):
        self._run(event)

    def disposing(self, event):
        pass


class Panel:
    def __init__(self, aura):
        self.aura = aura
        self.ctx = aura.ctx
        self.t = T.get(aura._lang(), T["en"])
        self.listeners = []
        self.model = self._create("com.sun.star.awt.UnoControlDialogModel")
        self.model.Width, self.model.Height = W, H
        self.model.Title = self.t["title"]
        self.y = {}
        self.dialog = None

    def _create(self, name):
        return self.ctx.ServiceManager.createInstanceWithContext(name, self.ctx)

    def add(self, kind, name, x, y, w, h, step=0, **props):
        m = self.model.createInstance(f"com.sun.star.awt.UnoControl{kind}Model")
        m.PositionX, m.PositionY, m.Width, m.Height, m.Step = x, y, w, h, step
        for k, v in props.items():
            if isinstance(v, (list, tuple)) and k in ("StringItemList", "SelectedItems"):
                v = uno.Any("[]string" if k == "StringItemList" else "[]short", tuple(v))
                uno.invoke(m, "setPropertyValue", (k, v))
            else:
                setattr(m, k, v)
        self.model.insertByName(name, m)
        return m

    # page helpers: one column of rows on the right
    def heading(self, step, text):
        self.y[step] = 8
        self.add("FixedText", f"h{step}", NAV + 12, 8, W - NAV - 20, 12, step, Label=text,
                 FontHeight=12.0, FontWeight=150.0)
        self.y[step] = 26

    def row(self, step, height=12):
        y = self.y[step]
        self.y[step] += height + 6
        return y

    def label(self, step, name, text, height=10, multiline=False):
        self.add("FixedText", name, NAV + 12, self.row(step, height), W - NAV - 20, height, step,
                 Label=text, MultiLine=multiline)

    def choice(self, step, name, caption, items, selected):
        y = self.row(step, 14)
        self.add("FixedText", name + "_l", NAV + 12, y + 2, 84, 10, step, Label=caption)
        self.add("ListBox", name, NAV + 100, y, W - NAV - 110, 14, step, Dropdown=True,
                 StringItemList=items, SelectedItems=[selected])

    def check(self, step, name, caption, state):
        self.add("CheckBox", name, NAV + 12, self.row(step, 12), W - NAV - 20, 12, step,
                 Label=caption, State=1 if state else 0)

    def button(self, step, name, caption, width=130):
        self.add("Button", name, NAV + 12, self.row(step, 14), width, 14, step, Label=caption)

    def build(self):
        t, prefs, aura = self.t, self.aura.settings(), self.aura
        self.add("ListBox", "nav", 6, 6, NAV, H - 34, 0, StringItemList=t["sections"],
                 SelectedItems=[0])
        self.add("FixedLine", "sep", NAV + 4, 6, 4, H - 34, 0, Orientation=1)

        self.heading(1, t["sections"][0])
        self.choice(1, "theme", t["theme"], [t["light"], t["dark"]], 0 if prefs["theme"] == "light" else 1)
        self.choice(1, "icons", t["icons"], [t["icons_" + k] for k in ICON_KEYS],
                    ICON_KEYS.index(prefs["icons"]) if prefs["icons"] in ICON_KEYS else 0)
        layouts = [k for k, _ in LAYOUT_KEYS]
        self.choice(1, "layout", t["layout"], [t[label] for _, label in LAYOUT_KEYS],
                    layouts.index(prefs["layout"]) if prefs["layout"] in layouts else 0)
        if sys.platform.startswith("linux"):
            self.check(1, "gtk", t["gtk"], prefs["gtk"])

        self.heading(2, t["sections"][1])
        self.label(2, "ribbon_intro", t["ribbon_intro"], 20, True)
        self.check(2, "extensions_tab", t["extensions_tab"], prefs["extensions_tab"])
        try:
            count = len(aura._extension_names())
        except Exception:
            count = 0
        self.label(2, "ext_count", t["extensions_found"].format(n=max(0, count - 1)))
        self.button(2, "refresh", t["refresh"])

        self.heading(3, t["sections"][2])
        self.check(3, "templates", t["templates"], prefs["templates"])
        try:
            fonts = all(f in aura._installed_families() for f in ("Inter", "Inter Display"))
        except Exception:
            fonts = True
        self.label(3, "fonts", t["font_ok"] if fonts else t["font_missing"])
        self.button(3, "open_templates", t["templates_open"])

        self.heading(4, t["sections"][3])
        self.check(4, "smart_paste", t["smart_paste"], prefs["smart_paste"])
        self.label(4, "paste_help", t["paste_help"], 30, True)

        self.heading(5, t["sections"][4])
        self.check(5, "tips", t["tips"], prefs["tips"])
        cache = min(range(len(CACHES)), key=lambda i: abs(CACHES[i] - int(prefs["graphic_cache"])))
        self.choice(5, "cache", t["cache"], t["cache_values"], cache)

        self.dictation_page(6, t, prefs)

        self.heading(7, t["sections"][6])
        self.label(7, "version", t["version"].format(v=aura.version()))
        self.label(7, "office", t["office"].format(v=aura.office_version()))
        self.label(7, "language", t["language"].format(v=_language_name(aura._locale())))
        self.label(7, "status", t["status_on"] if aura.is_applied() else t["status_off"])
        self.button(7, "restore", t["restore"], 150)
        self.button(7, "uninstall", t["uninstall"], 150)

        # footer: status line + actions, always visible
        self.add("FixedLine", "footer", 6, H - 26, W - 12, 4, 0)
        self.add("FixedText", "message", 8, H - 18, W - 196, 12, 0, Label="")
        self.add("Button", "restart", W - 186, H - 20, 70, 14, 0, Label=t["restart"])
        self.add("Button", "close", W - 112, H - 20, 50, 14, 0, Label=t["close"], PushButtonType=2)
        self.add("Button", "apply", W - 58, H - 20, 52, 14, 0, Label=t["apply"], DefaultButton=True)
        self.model.Step = 1

    def dictation_page(self, step, t, prefs):
        import aura_dictation
        import aura_voice
        self.heading(step, t["sections"][step - 1])
        info = aura_dictation.install_info(self.aura)
        status = t["d_engine_on"].format(m=info.get("model", "Whisper")) if info else t["d_engine_off"]
        self.add("FixedText", "d_status", NAV + 12, 26, W - NAV - 20, 10, step, Label=status)
        x = NAV + 12
        for name, label, width in (("d_install", t["d_update"] if info else t["d_install"], 76),
                                   ("d_start", t["d_start"], 80), ("d_remove", t["d_remove"], 56)):
            self.add("Button", name, x, 39, width, 14, step, Label=label, Enabled=name != "d_remove" or bool(info))
            x += width + 4
        self.y[step] = 60
        langs = ["auto"] + list(aura_voice.LANGUAGES)
        self.choice(step, "d_language", t["d_language"],
                    [t["d_auto"]] + [f"{v[0]} — {v[1]}" if v[0] != v[1] else v[0]
                                     for v in aura_voice.LANGUAGES.values()],
                    langs.index(prefs["dictation_language"]) if prefs["dictation_language"] in langs else 0)
        models = aura_dictation.MODELS
        self.choice(step, "d_model", t["d_model"], t["d_models"],
                    models.index(prefs["dictation_model"]) if prefs["dictation_model"] in models else 0)
        devices = aura_dictation.DEVICES
        self.choice(step, "d_device", t["d_device"], t["d_devices"],
                    devices.index(prefs["dictation_device"]) if prefs["dictation_device"] in devices else 0)
        y = self.row(step, 14)
        half = (W - NAV - 20) // 2
        self.add("FixedText", "d_yoruba_l", NAV + 12, y + 2, 40, 10, step, Label=t["d_yoruba"])
        self.add("ListBox", "d_yoruba", NAV + 54, y, half - 46, 14, step, Dropdown=True,
                 StringItemList=t["d_yorubas"], SelectedItems=[1 if prefs["dictation_yoruba"] == "mms" else 0])
        self.add("FixedText", "d_chinese_l", NAV + 16 + half, y + 2, 40, 10, step, Label=t["d_chinese"])
        self.add("ListBox", "d_chinese", NAV + 58 + half, y, half - 50, 14, step, Dropdown=True,
                 StringItemList=t["d_chineses"],
                 SelectedItems=[1 if prefs["dictation_chinese"] == "traditional" else 0])
        y = self.row(step, 14)
        self.add("FixedText", "d_glossary_l", NAV + 12, y + 2, 84, 10, step, Label=t["d_glossary"])
        self.add("Edit", "d_glossary", NAV + 100, y, W - NAV - 110, 14, step, Text=prefs["dictation_glossary"],
                 MaxTextLen=400)
        self.y[step] -= 2
        self.check(step, "d_commands", t["d_commands"], prefs["dictation_commands"])
        self.y[step] -= 4
        self.check(step, "d_shortcut", t["d_shortcut"], prefs["dictation_shortcut"])

    def dictation_values(self):
        import aura_dictation
        import aura_voice
        m = self.model.getByName
        sel = lambda name: (m(name).SelectedItems or (0,))[0]  # noqa: E731
        return {
            "dictation_language": (["auto"] + list(aura_voice.LANGUAGES))[sel("d_language")],
            "dictation_model": aura_dictation.MODELS[sel("d_model")],
            "dictation_device": aura_dictation.DEVICES[sel("d_device")],
            "dictation_yoruba": ("whisper", "mms")[sel("d_yoruba")],
            "dictation_chinese": ("simplified", "traditional")[sel("d_chinese")],
            "dictation_glossary": m("d_glossary").Text.strip()[:400],
            "dictation_commands": m("d_commands").State == 1,
            "dictation_shortcut": m("d_shortcut").State == 1,
        }

    def _dictation_save(self):
        import aura_dictation
        before = self.aura.settings()
        prefs = self.aura.save_settings(self.dictation_values())
        if before["dictation_shortcut"] != prefs["dictation_shortcut"]:
            aura_dictation.bind_shortcut(self.aura, prefs["dictation_shortcut"])
        return prefs

    def _dictation_install(self):
        import aura_dictation
        prefs = self._dictation_save()
        buttons = ("d_install", "d_start", "d_remove", "apply", "close")
        for name in buttons:
            self.model.getByName(name).Enabled = False
        self._say(aura_dictation.text(self.aura, "installing"))

        def done(message, info):
            if self.dialog is None:
                return
            for name in buttons:
                self.model.getByName(name).Enabled = True
            self._say(message)
            if info:
                self.model.getByName("d_status").Label = self.t["d_engine_on"].format(m=info.get("model", "Whisper"))
                self.model.getByName("d_install").Label = self.t["d_update"]

        def work():
            try:
                info = aura_dictation.install(
                    self.aura, lambda line: aura_dictation.on_main(self.ctx, lambda: self._say(line[:110])), prefs)
                message = aura_dictation.text(self.aura, "installed")
            except Exception as e:
                info, message = None, "⚠ " + aura_dictation.text(self.aura, "install_failed", e=e)
            aura_dictation.on_main(self.ctx, lambda: done(message, info))
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _dictation_start(self):
        import aura_dictation
        self._dictation_save()
        self.dialog.endExecute()
        aura_dictation.start(self.aura)

    def _dictation_remove(self):
        import aura_dictation
        aura_dictation.remove(self.aura)
        self.model.getByName("d_status").Label = self.t["d_engine_off"]
        self.model.getByName("d_install").Label = self.t["d_install"]
        self.model.getByName("d_remove").Enabled = False
        self._say(aura_dictation.text(self.aura, "removed"))

    def show(self, parent=None):
        self.build()
        dialog = self._create("com.sun.star.awt.UnoControlDialog")
        dialog.setModel(self.model)
        toolkit = self._create("com.sun.star.awt.Toolkit")
        dialog.createPeer(toolkit, parent)
        self.dialog = dialog

        def on(name, method, fn):
            listener = _Listener(fn, lambda e: self._say(f"⚠ {e}"))
            self.listeners.append(listener)
            getattr(dialog.getControl(name), method)(listener)

        on("nav", "addItemListener", lambda e: self._go(e.Selected + 1))
        for name, fn in (("apply", self._apply), ("restart", self._restart), ("refresh", self._refresh),
                         ("open_templates", self._templates), ("restore", self._restore),
                         ("uninstall", self._uninstall), ("d_install", self._dictation_install),
                         ("d_start", self._dictation_start), ("d_remove", self._dictation_remove)):
            on(name, "addActionListener", lambda e, f=fn: f())
        dialog.execute()
        self.dialog = None
        dialog.dispose()

    def _go(self, step):
        if step >= 1:
            self.model.Step = step

    def _say(self, text):
        self.model.getByName("message").Label = text

    def values(self):
        m = self.model.getByName
        sel = lambda name: (m(name).SelectedItems or (0,))[0]  # noqa: E731
        out = {
            "theme": ("light", "dark")[sel("theme")],
            "icons": ICON_KEYS[sel("icons")],
            "layout": LAYOUT_KEYS[sel("layout")][0],
            "extensions_tab": m("extensions_tab").State == 1,
            "templates": m("templates").State == 1,
            "smart_paste": m("smart_paste").State == 1,
            "tips": m("tips").State == 1,
            "graphic_cache": CACHES[sel("cache")],
        }
        if self.model.hasByName("gtk"):
            out["gtk"] = m("gtk").State == 1
        return out

    def _apply(self):
        self._dictation_save()
        self.aura.save_settings(self.values())
        self.aura.apply(silent=True)
        self.model.getByName("status").Label = self.t["status_on"]
        self._say(self.t["applied"])

    def _restart(self):
        self.dialog.endExecute()
        self.aura.restart()

    def _refresh(self):
        self.aura.save_settings({"extensions_tab": self.model.getByName("extensions_tab").State == 1})
        if self.aura.is_applied():
            self.aura.refresh(silent=True, force=True)
        self._say(self.t["refreshed"])

    def _templates(self):
        self.dialog.endExecute()
        self.aura.dispatch(".uno:NewDoc")

    def _restore(self):
        self.aura.restore(silent=True)
        self.model.getByName("status").Label = self.t["status_off"]
        self._say(self.t["restored"])

    def _uninstall(self):
        toolkit = self._create("com.sun.star.awt.Toolkit")
        box = toolkit.createMessageBox(self.dialog.getPeer(),
                                       uno.Enum("com.sun.star.awt.MessageBoxType", "QUERYBOX"),
                                       3, "Aura", self.t["uninstall_confirm"])
        if box.execute() != 2:
            return
        self.dialog.endExecute()
        self.aura.uninstall()


LANGUAGE_NAMES = {"fr": "Français", "en": "English", "de": "Deutsch", "es": "Español", "it": "Italiano",
                  "pt": "Português", "nl": "Nederlands", "pl": "Polski", "ru": "Русский", "ja": "日本語",
                  "zh": "中文", "ar": "العربية", "tr": "Türkçe", "sv": "Svenska", "cs": "Čeština"}


def _language_name(tag):
    name = LANGUAGE_NAMES.get(tag.split("-")[0].lower())
    return f"{name} ({tag})" if name else tag


def show(aura):
    frame = aura._create("com.sun.star.frame.Desktop").getCurrentFrame()
    parent = frame.getContainerWindow() if frame is not None else None
    Panel(aura).show(parent)


def welcome(aura, parent=None):
    """First run: a short introduction with one-click choices."""
    t = T.get(aura._lang(), T["en"])
    smgr, ctx = aura.ctx.ServiceManager, aura.ctx
    model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", ctx)
    model.Width, model.Height, model.Title = 260, 128, t["welcome_title"]

    def add(kind, name, x, y, w, h, **props):
        m = model.createInstance(f"com.sun.star.awt.UnoControl{kind}Model")
        m.PositionX, m.PositionY, m.Width, m.Height = x, y, w, h
        for k, v in props.items():
            setattr(m, k, v)
        model.insertByName(name, m)

    add("FixedText", "title", 12, 10, 236, 14, Label=t["welcome_title"], FontHeight=14.0, FontWeight=150.0)
    add("FixedText", "text", 12, 30, 236, 66, Label=t["welcome"], MultiLine=True)
    add("Button", "light", 12, 104, 84, 15, Label=t["welcome_light"], DefaultButton=True)
    add("Button", "dark", 100, 104, 84, 15, Label=t["welcome_dark"])
    add("Button", "later", 192, 104, 56, 15, Label=t["later"], PushButtonType=2)
    dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    dialog.setModel(model)
    if parent is None:
        frame = aura._create("com.sun.star.frame.Desktop").getCurrentFrame()
        parent = frame.getContainerWindow() if frame is not None else None
    dialog.createPeer(aura._create("com.sun.star.awt.Toolkit"), parent)
    choice = []
    listeners = []
    for name in ("light", "dark"):
        listener = _Listener(lambda e, n=name: (choice.append(n), dialog.endExecute()))
        listeners.append(listener)
        dialog.getControl(name).addActionListener(listener)
    dialog.execute()
    dialog.dispose()
    if choice:
        aura.apply(choice[0])
