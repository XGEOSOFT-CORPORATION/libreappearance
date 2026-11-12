# Aura — une apparence moderne pour LibreOffice

**Aura** est une extension (`.oxt`) pour **LibreOffice ≥ 24.2** qui donne à Writer, Calc,
Impress et Draw une interface légère et épurée, et des documents d'un niveau Premium.

| | Ce qu'Aura apporte |
|---|---|
| **Icônes** | Thèmes *Aura* (clair) et *Aura dark* : les 4 520 icônes de LibreOffice redessinées dans une palette ardoise + indigo. Couverture complète, aucune icône manquante. |
| **Couleurs** | Schémas *Aura Light* / *Aura Dark* : fond d'application doux, page flottante sans traits de limites, grille Calc discrète, liens et repères en indigo. |
| **Habillage (Linux)** | Thèmes GTK *Aura* / *Aura-dark* appliqués **à LibreOffice seul** : police Inter, surfaces blanches ou ardoise, accent indigo, champs et boutons arrondis, onglets soulignés, menus et infobulles redessinés, barres de défilement fines. Le reste du bureau n'est pas modifié. |
| **Ruban** | Onglets compacts réorganisés dans Writer, Calc, Impress et Draw (« Accueil », « Extensions »…). L'onglet Accueil est allégé des doublons ; un contrôle au build garantit que **chaque commande du ruban d'origine reste dans le ruban**. |
| **Documents** | Modèles Writer, Calc et Impress : typographie Inter, hiérarchie de titres, tableaux à filets fins, styles de cellules (KPI, monétaire, total…), masques 16:9 clair / nuit / accent. |

## Installation

```bash
make install        # construit dist/Aura-<version>.oxt et l'installe avec unopkg
```

Ou : *Outils ▸ Gestionnaire des extensions ▸ Ajouter* et choisir `dist/Aura-<version>.oxt`.

Puis **Outils ▸ Aura ▸ Appliquer Aura (clair | sombre)**, fermer complètement LibreOffice et le
relancer **depuis le menu des applications** (les lanceurs Aura démarrent LibreOffice avec le thème
GTK Aura ; lancé depuis un terminal, `GTK_THEME=Aura libreoffice`).
**Outils ▸ Aura ▸ Restaurer l'apparence d'origine** remet exactement vos réglages précédents
(ils sont sauvegardés dans `<profil>/user/libreappearance/backup.json`).

Police recommandée : [Inter](https://rsms.me/inter/) (OFL), avec *Inter Display*.

## Construire

Prérequis : LibreOffice ≥ 24.2, un Python qui peut `import uno` (sous Debian/Ubuntu :
`/usr/bin/python3`, paquet `python3-uno`), `make`.

```bash
make            # icônes + schémas de couleurs + modèles + exemples, puis dist/Aura-<version>.oxt
make test       # installe l'extension dans un profil jetable et vérifie appliquer / restaurer
make samples    # régénère seulement les modèles et build/samples/*.pdf pour la revue visuelle
```

Toutes les couleurs et polices viennent de [design/tokens.json](design/tokens.json) : modifier
un token puis `make` met à jour icônes, couleurs d'application et modèles d'un coup.

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) pour le fonctionnement interne.

## Licences

Code : MIT (voir [LICENSE](LICENSE)). Les thèmes d'icônes sont dérivés de Colibre
(© The Document Foundation, CC BY-SA 4.0) et restent sous CC BY-SA 4.0.

## Aperçu

![Ruban réorganisé](docs/previews/ribbons.png)
![Dialogue](docs/previews/dialog.png)
![Writer sombre](docs/previews/writer-dark.png)
![Writer](docs/previews/writer.png)
![Calc](docs/previews/calc.png)
![Impress](docs/previews/impress.png)
![Masques Impress](docs/previews/slides.png)
