# Architecture

```
design/tokens.json          source unique : rampes de couleurs, mapping des icônes,
                            schémas de couleurs, typographie, couleurs de documents
tools/
  build_icons.py            Colibre SVG (installé avec LibreOffice) -> images_aura[_dark]_svg.zip
  build_registry.py         tokens -> registry/ColorSchemes.xcu
  build_gtk.py              tokens.chrome + src/gtk/aura.css -> gtk/Aura, gtk/Aura-dark (GTK 3)
  build_ribbon.py           notebookbar_compact.ui installé + design/ribbon.json -> ui/<module>/
                            (onglets scindés par thème, commandes mortes corrigées ; échoue si
                            une commande du ruban d'origine disparaît du ruban)
  build_templates.py        pilote un LibreOffice headless (profil jetable) via UNO
                            -> templates/Aura/*.ott|ots|otp (+ exemples et PDF)
  build_oxt.py              src/extension + assets générés -> dist/Aura-<version>.oxt
  test_extension.py         installe l'oxt dans un profil jetable et vérifie le tout
  test_commands.py          chaque commande des rubans exécutable dans son module (comparé au
                            ruban d'origine : aucune régression, toute commande ajoutée passe)
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
                            aura_table.py (tableaux : Calc/HTML -> Writer/Impress)
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
