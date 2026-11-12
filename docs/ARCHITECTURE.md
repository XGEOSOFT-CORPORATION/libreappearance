# Architecture

```
design/tokens.json          source unique : rampes de couleurs, mapping des icônes,
                            schémas de couleurs, typographie, couleurs de documents
tools/
  build_icons.py            Colibre SVG (installé avec LibreOffice) -> images_aura[_dark]_svg.zip
  build_registry.py         tokens -> registry/ColorSchemes.xcu
  build_gtk.py              tokens.chrome + src/gtk/aura.css -> gtk/Aura, gtk/Aura-dark (GTK 3)
  build_ribbon.py           vérifie design/ribbon.json sur le ruban de ce LibreOffice et le livre
                            (ui/ribbon.json) ; l'extension l'applique au ruban de la version
                            installée chez l'utilisateur
  build_templates.py        pilote un LibreOffice headless (profil jetable) via UNO
                            -> templates/Aura/*.ott|ots|otp (+ exemples et PDF)
  build_oxt.py              src/extension + assets générés -> dist/Aura-<version>.oxt
  test_extension.py         installe l'oxt dans un profil jetable et vérifie le tout
  test_commands.py          chaque commande des rubans exécutable dans son module (comparé au
                            ruban d'origine : aucune régression, toute commande ajoutée passe)
  test_dictation.py         commandes vocales et espacement dans les 7 langues (sans LibreOffice)
  test_voice_office.py      dictée de bout en bout : vrai moteur sur des WAV -> Writer et Calc
  test_table_html.py        analyse du HTML d'Excel (classes CSS, bordures en pt, fusions)
src/extension/              fichiers statiques de l'extension
  description.xml           identifiant org.libreappearance.aura, LibreOffice >= 24.2
  Paths.xcu                 ajoute %origin%/iconsets et %origin%/templates aux chemins
  registry/Addons.xcu       menu Outils ▸ Aura
  registry/Jobs.xcu         job de démarrage : régénère les rubans (langue, extensions)
  registry/Accelerators.xcu Ctrl+V dans Writer -> collage de tableau fidèle
  python/aura.py            composant UNO (XJobExecutor, XJob) : appliquer / restaurer / actualiser,
                            collage de tableau, polices
  python/pythonpath/        aura_ribbon.py (rubans, onglet Extensions, langue),
                            aura_table.py (tableaux : Calc/HTML -> Writer/Impress),
                            aura_dictation.py (dictée : moteur, fenêtre, insertion),
                            aura_voice.py (commandes vocales, espacement ; sans UNO),
                            aura_voice_engine.py (micro -> Whisper -> JSON, processus séparé),
                            aura_panel.py (Panneau Aura, accueil), aura_icons.py (icônes)
```

## Ce que l'extension peut — et ne peut pas — changer en 24.2

| Levier | Mécanisme | Portée |
|---|---|---|
| Icônes | `Paths/Iconset` + `images_<id>_svg.zip` | toute l'interface |
| Couleurs d'application | `UI/ColorScheme/ColorSchemes` | fond, page, grille, repères, liens |
| Disposition | `UI.ToolbarMode` + `UI.<Module>WindowState` | ruban compact, barres masquées |
| Modèles par défaut | `Setup/Office/Factories/*/ooSetupFactoryTemplateFile` | nouveaux documents |
| Ruban | `$(user)/config/soffice.cfg/modules/<m>/ui/notebookbar_compact.ui` | onglets renommés, Accueil allégé |
| Habillage (Linux, VCL gtk3) | thème GTK `Aura` + lanceurs `env GTK_THEME=Aura` dans `~/.local/share` | widgets, dialogues, menus, police d'interface |
| Habillage (Windows, macOS) | widgets natifs du système | **hors de portée en 24.2** |

Le thème GTK est Adwaita (intégré à GTK, toujours présent) + les couleurs `@aura_*` + les règles
de `src/gtk/aura.css`. Il n'est utilisé que par les processus lancés avec `GTK_THEME=Aura` : le
reste du bureau garde son thème. En mode sombre, l'interface et le fond sont sombres mais la page
reste blanche, pour que les couleurs des documents restent exactes (LibreOffice n'inverse que les
couleurs « automatiques »).

## Ruban : garantie de couverture

`build_ribbon.py` compare les commandes `.uno:` visibles du ruban d'origine (onglets et menus
déroulants des onglets) à celles du ruban Aura. S'il en manque une, le build s'arrête : une
fonction ne peut être retirée de l'Accueil que si elle reste ailleurs dans le ruban.

## Appliquer / restaurer

`aura.py` prend un instantané des réglages touchés (thème d'icônes, schéma de couleurs, mode
de barre d'outils et visibilité des barres par module, modèles par défaut) et l'écrit dans
`$(user)/libreappearance/backup.json` **seulement s'il n'existe pas déjà** : le premier
instantané est l'apparence d'origine, même après plusieurs applications clair/sombre.
Restaurer réécrit ces valeurs et supprime la sauvegarde.

`UI.ToolbarMode/Applications/<App>/Active` contient l'argument du mode (`notebookbar_compact.ui`,
`Default`…), qui est aussi l'argument de la commande `.uno:ToolbarMode` utilisée pour basculer
la fenêtre courante immédiatement.

Les modèles sont copiés dans `$(user)/libreappearance/templates/` : leur chemin reste stable
même si l'extension est réinstallée (le cache `uno_packages` change de nom à chaque fois).

## Fichiers posés hors de la configuration

Ruban, thèmes GTK et lanceurs sont listés dans `$(user)/libreappearance/files.json` ; un fichier
existant est mis de côté avant d'être remplacé. Restaurer supprime ce qu'Aura a créé et remet
ce qu'il a remplacé.

## Icônes

Chaque couleur des SVG Colibre est remplacée : d'abord via les `overrides` explicites des
tokens (les ~20 couleurs qui couvrent l'essentiel), sinon par la teinte de la rampe Aura de
même famille (ardoise, indigo, ciel, violet, rose, ambre, émeraude) la plus proche en
luminosité. Les formes ne changent pas, donc la couverture reste complète.

## Langue de l'interface

Les onglets créés par Aura portent un couple `[msgctxt, msgid]` qui existe déjà dans le catalogue
de LibreOffice pour le module (`sw`, `sc`, `sd`). À l'application, `aura_ribbon.localize` lit le
catalogue de la langue d'interface active (`$(prog)/resource/<langue>/LC_MESSAGES/*.mo`) et écrit
le libellé traduit. Les corrections propres à une langue (en français « Origine » -> « Accueil »)
sont dans `ribbon.json` (`labels`). Le job de démarrage compare langue, extensions et version à
l'état enregistré dans `files.json` et régénère les rubans s'ils ont changé.

## Onglet Extensions

Aura lit `AddonUI` (`OfficeNotebookBar`, `OfficeToolBar`, `OfficeToolbarMerging`), regroupe les
commandes par extension (le nom vient des fichiers `.xcu` que chaque extension installée déclare),
filtre par module, puis écrit un groupe titré par extension : boutons texte directs, ou menu
« Nom ▾ » pour les groupes les plus larges quand tout ne tient pas dans la largeur de la fenêtre.
Les menus d'extensions restent accessibles par le bouton « Extension ▾ » de LibreOffice.

## Collage de tableaux

Depuis Calc, le presse-papiers contient le classeur de la plage copiée, mais avec les définitions
**par défaut** des styles de cellule intégrés (défaut de LibreOffice) : Aura retrouve donc la
sélection d'origine dans le document ouvert (même contenu) et la lit directement ; à défaut, il
utilise le classeur du presse-papiers. Depuis Excel ou le web, il analyse le HTML et son CSS.
Le tableau est recréé nativement (`TextTable` dans Writer, `TableShape` dans Impress/Draw), dans
un seul pas d'annulation.

## Windows et macOS

Tout passe par la configuration et le Python fourni avec LibreOffice ; seuls le thème GTK et les
lanceurs sont propres à Linux. Le mode clair/sombre des fenêtres utilise
`Common/Misc/Appearance`. Inter est installée dans les polices de l'utilisateur
(`%LOCALAPPDATA%\Microsoft\Windows\Fonts` + registre HKCU, `~/Library/Fonts`,
`~/.local/share/fonts`) seulement si elle manque, et retirée par Restaurer.

## Compatibilité 24.2 et suivantes

Rien n'est figé sur une version : les rubans sont produits au moment de l'application à partir du
`notebookbar_compact.ui` **installé** (`$BRAND_BASE_DIR/$BRAND_SHARE_SUBDIR/...`, valable aussi sur
macOS) ; un onglet ou une section absente est ignorée, et si le résultat masquait une seule commande
du ruban d'origine, le module garde le ruban de LibreOffice. L'état enregistré inclut la version
de LibreOffice : après une mise à jour, le job de démarrage reconstruit rubans et icônes (à partir
de Colibre installé). Les réglages qui peuvent ne pas exister selon la version sont écrits « si
présents ». Le Python des composants vise 3.8+ et n'utilise que la bibliothèque standard.

## Sécurité

- **Suppression** : `files.json` peut être modifié par quiconque accède au profil ; Aura ne supprime
  ou ne déplace qu'un fichier dont le chemin correspond à ses propres emplacements (rubans du
  profil, thèmes `Aura*`, lanceurs `libreoffice-*.desktop`, polices `Inter*`, sauvegardes).
- **Presse-papiers** : le classeur intégré est chargé caché, en lecture seule, filtre `calc8`
  imposé, macros jamais exécutées, liens jamais mis à jour ; HTML limité (20 Mo, 5 000 cellules,
  fusions ≤ 200).
- **Commandes** : les URL `service:…Aura?…` peuvent être déclenchées par un document ; Restaurer
  demande confirmation, la désinstallation n'existe que dans le panneau.
- **Processus** : le redémarrage passe ses valeurs en arguments (`sh -c script -- pid thème programme`),
  jamais dans le texte du script.
- **Préférences** : chaque valeur de `settings.json` est validée (type et valeurs permises).
- **Ctrl+V** : posé par l'application et rendu à `.uno:Paste` par la restauration ; aucun raccourci
  statique, donc si Python manque, rien n'est cassé.
- **Profils multiples** : un thème ou lanceur Aura déjà présent (autre profil) est mis à jour sur
  place sans être revendiqué.

## Dictée vocale

```
LibreOffice (aura_dictation)                  processus séparé (venv du profil)
  Ctrl+Alt+Espace -> Session.start ──Popen──>  aura_voice_engine.py
                                               micro (PortAudio, sinon pw-record / parecord /
                                               arecord / ffmpeg) -> découpage sur les pauses
                                               -> Whisper (faster-whisper, GPU si possible)
  thread lecteur <──── JSON par ligne ──────   status / level / partial / final / error
  AsyncCallback -> thread principal
  aura_voice.parse : commande ou texte ?
  insertion : Writer (curseur), Calc (cellule), Impress/Draw (forme)
```

Le moteur ne tourne jamais dans le processus de LibreOffice : un modèle de plusieurs gigaoctets ou une
bibliothèque CUDA ne peuvent ni le bloquer ni le faire tomber. Il s'arrête quand son entrée standard se
ferme, donc il ne survit jamais à LibreOffice. Les documents ne sont touchés que depuis le thread principal
(`com.sun.star.awt.AsyncCallback`).

**Langue.** En mode automatique, la langue est détectée à chaque phrase mais seulement parmi les 7 langues
de dictée. Une phrase courte (< 1,2 s) garde la langue précédente. On ne change de langue que si la
nouvelle est nettement plus probable (+0,25), sinon un « OK » isolé ferait basculer la dictée.

**Qualité.** Le prompt de Whisper contient la fin de la phrase précédente dans la même langue, le vocabulaire
de l'utilisateur, et une amorce par langue : caractères simplifiés ou traditionnels, ponctuation japonaise,
signes diacritiques du yoruba. Les hallucinations connues de Whisper sur le silence (« Sous-titres réalisés
par la communauté d'Amara.org », « ご視聴ありがとうございました »…) sont écartées.

**Espacement.** `aura_voice.join` regarde le texte avant le curseur. Pas d'espace en japonais et en chinois,
ni avant la ponctuation fermante. Espace insécable avant `; : ! ? »` et après `«` en français. Majuscule en
début de phrase, et minuscule au premier mot d'une phrase coupée par une pause (sauf sigles et « I » anglais).

**GPU.** Avec une carte NVIDIA, l'installation ajoute cuBLAS et cuDNN (paquets pip `nvidia-*`) que le
moteur charge par leur chemin. Si la carte ne peut pas exécuter le modèle, le moteur repasse sur le
processeur (int8) tout seul.
