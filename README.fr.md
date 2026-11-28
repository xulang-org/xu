<p align="center">
  <a href="https://xulang.org/fr/"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">Le Langage de Programmation Xu</h1>

<p align="center">
  <b>La concurrence à la Go alliée aux performances Zero-GC de C/Rust</b><br>
  <sub>Un langage système sûr en mémoire à la compilation, conçu pour le haut débit, la faible latence et les applications modernes.</sub>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ja.md">日本語</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <b>Français</b> | <a href="README.de.md">Deutsch</a> | <a href="README.ru.md">Русский</a> | <a href="README.pt-BR.md">Português</a>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org/fr/"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/fr/benchmarks/"><img src="https://img.shields.io/badge/Benchmarks-72%20Workloads-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org/fr/playground/">🌐 <b>Bac à Sable en Ligne (Sans Installation)</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/fr/benchmarks/">⚡ <b>Tableau de Benchmarks (72 Charges)</b></a> &nbsp;•&nbsp;
  <a href="#quick-start">🚀 <b>Démarrage Rapide en 30s</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.md">📋 <b>Notes de Version</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>Télécharger les Installeurs</b></a>
</p>

---

> **Téléchargements officiels du SDK** : [GitHub Releases](https://github.com/xulang-org/xu/releases) — Consultez les [Notes de version (RELEASES.md)](RELEASES.md) pour le journal complet, les changements incompatibles et les guides de migration.

## ⚡ Xu en un Coup d'Œil (Des Faits, Pas des Discours)

Pas de code répétitif complexe. Pas de gymnastique d'annotations explicites de durées de vie. Découvrez la syntaxe claire et moderne de Xu en 15 lignes de code :

```xu
@main
#errors

// Contrôle de flux symbolique : `<<` retourne, `>>` lève une erreur ; sans imbrication Result/unwrap
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) >>> (err) { << } // Gestion locale sûre obligatoire sans `if err != nil`
    ch <- val                                 // Échange de messages par canaux typés
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // Le mot-clé natif `xu` lance une coroutine légère
    xu worker("memory", ch)
    println(<-ch + <-ch)     // Agrégation fan-in sur les canaux
    << 0                     // Libération déterministe, zéro pause GC, compilation AOT native statique
}
```

> **Pourquoi les développeurs l'adoptent** :
> 1. **Contrôle de flux symbolique** : `<<` retourne, `>>` lève une erreur, `<<<` quitte. Adieu les mots-clés verbeux hérités.
> 2. **Gestion d'erreurs ergonomique** : Traitée au point d'appel avec `>>> (err) { ... }` (ou propagée avec `>>>`). Élimine les `if err != nil` envahissants et les plantages catastrophiques de `unwrap()` à l'exécution.
> 3. **Concurrence légère native** : Les coroutines `xu worker()` + canaux `chan` offrent une concurrence aussi fluide qu'en Go.
> 4. **Sûreté statique à la compilation** : Suivie par inférence de propriété et d'emprunt. **Aucun ramasse-miettes (Zero-GC)**, zéro pause et consommation mémoire déterministe ultra-sobre.

Un nom de référence modifiable `r: $&T` peut satisfaire une attente `&T` : écrivez `read(r)` ou `let view: &T = r`. La vue partagée fige le parent contre toute écriture ou déplacement conflictuel jusqu'à sa dernière utilisation, y compris pour les vues stockées et les valeurs de retour. Les arguments partagés et modifiables en conflit dans un même appel sont rejetés. La rétrogradation implicite exige actuellement un nom de référence local et un type pointé direct identique. Déclarez une liaison mutable une seule fois avec `$x := value` (ou `let $x: T = value`), puis utilisez simplement `x`. Les valeurs ordinaires requièrent `&x` pour un emprunt partagé ou `$&x` pour un emprunt modifiable, dont le type de référence est `$&T`. Réutilisez les noms de référence tels quels (`r`) ou écrivez `&*r` pour un réemprunt explicite. L'emprunt automatique à partir de valeurs ordinaires n'est pas implémenté.
Contrats matériels bas niveau et bare-metal : les noyaux d'OS et pilotes matériels manipulent des pointeurs bruts `*raw T`, dont le déréférencement exige des blocs explicites `unsafe { ... }` (par ex. `p := addr as *raw u32; unsafe { *p = val }`), totalement ignorés par l'inférence d'emprunt ; le MMIO emploie les barrières intégrées `volatile_read` / `volatile_write` ; la disposition mémoire des structures accepte l'alignement `@repr("C", align: N)` et la compacité sans bourrage `@repr("C", packed)` ; les sources bare-metal déclarent `$freestanding` pour couper tout lien avec les appels système hôtes et la libc.

Consultez le [Guide d'emprunt et du modèle mémoire](https://xulang.org/fr/docs/lang/memory/) pour les règles en vigueur.

---

## 🎯 Points de Douleur et « Pourquoi Xu ? »

En tant qu'ingénieurs concevant des systèmes et services haute performance, nous sommes sans cesse contraints à des compromis bancals :

### 1. Les dilemmes que nous résolvons

- **Point de douleur 1 : Pics de latence du ramasse-miettes et inflation mémoire**
  - *État actuel* : Go et Java sont productifs, mais les pauses STW du GC et la gigue de latence imprévisible sont rédhibitoires pour les passerelles basse latence, les moteurs de trading et l'embarqué.
  - *Réponse de Xu* : **Runtime Zero-GC**. Compilation AOT pure. La propriété suit la mémoire à la compilation et la libère de façon déterministe en fin de portée. Zéro pause, zéro pic GC.
- **Point de douleur 2 : La lutte contre « l'enfer des annotations explicites de lifetime »**
  - *État actuel* : C/C++ expose aux pointeurs pendants, corruptions mémoire et failles UAF. Rust est sûr, mais les paramètres explicites de durée de vie (`'a`, `'b`) et la gymnastique de types ralentissent fortement le développement.
  - *Réponse de Xu* : **Inférence implicite de propriété et vérification d'emprunt**. Aucune annotation explicite de durée de vie dans le code applicatif. La sémantique naturelle par valeur des slices réunit sûreté et vélocité.
- **Point de douleur 3 : Code répétitif envahissant et couches d'enveloppes d'erreurs**
  - *État actuel* : Les bases de code Go regorgent de `if err != nil`. Rust empile de multiples enveloppes `Result<T, E>` / `Option`.
  - *Réponse de Xu* : **L'opérateur symbolique `>>` combiné à la gestion obligatoire `>>> (err) { ... }`**, offrant une propagation d'erreurs légère, lisible et sûre.
- **Point de douleur 4 : Chaînes d'outils fragmentées et installation laborieuse**
  - *État actuel* : Assembler CMake, Make, gestionnaires de paquets et éditeurs de liens propres à chaque plateforme reste notoirement fragile.
  - *Réponse de Xu* : **Boucle fermée en un seul binaire**. Tout — compilateur, exécuteur de tests, formateur (`xu fmt`), générateur de documentation (`xu doc`) et assistants d'installation GUI auto-rendus — est intégré.

### 2. Comparaison technique sans compromis

| Critère clé | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **Gestion mémoire** | `malloc`/`free` manuel<br>*(Fuites et pointeurs pendants)* | GC à l'exécution<br>*(Pauses STW et inflation mémoire)* | Propriété à la compilation<br>*(Annotations explicites `'a`)* | **Propriété à la compilation<br>(Zero-GC / Libération déterministe)** |
| **Surcoût runtime** | Abstractions à coût nul | Lourd (moteur GC + ordonnanceur) | Abstractions à coût nul | **Coût nul (Sans moteur GC / Code machine natif pur)** |
| **Charge cognitive** | Vulnérable aux UB et courses | Simple, mais paniques `nil` persistantes | Courbe abrupte (combats avec le borrow checker) | **Minimale (Sans annotations lifetime / Flux symbolique clair)** |
| **Modèle de concurrence** | Threads OS / Bibliothèques externes | Coroutines CSP (`go`) + canaux (`chan`) | Threads / Runtimes Async (coloration de fonctions) | **Coroutines légères natives (`xu`) + `chan` typés** |
| **Gestion d'erreurs** | Codes d'erreur / Exceptions *(Implicite)* | `if err != nil` *(Code répétitif)* | `Result<T, E>` + opérateur `?` | **Flux symbolique : `>>` levée + `or` obligatoire** |
| **Contrôle de flux** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / Expressions finales | **Flux symbolique : `<<` retour / `>>` erreur / `<-` rupture** |
| **Cohésion des outils** | Fragmentée (CMake/Make/Conan) | Intégrée d'office | Intégrée (Cargo) | **Binaire unique (build/test/fmt/doc intégrés)** |
| **Installation multiplateforme** | Dépendances complexes de toolchain/linker | Installeur officiel / PATH manuel | Nécessite rustup et scripts réseau externes | **Assistants GUI autonomes / Installation en un clic** |
| **Bare-metal & noyaux** | Édition de liens manuelle et asm inline, non sûr | Non pris en charge (lié au GC/runtime) | Pris en charge (`no_std`), mais lifetimes lourds | **Support natif (`freestanding` / `#core`)<br>Destruction déterministe Zero-GC + Lifetimes inférés** |

---

<a id="quick-start"></a>
## 🚀 Démarrage Rapide Sans Friction

### Option 1 : Bac à sable navigateur instantané (Sans installation)

Accédez directement au **[Bac à Sable en Ligne xulang.org](https://xulang.org/fr/playground/)**. Le bac à sable WebAssembly côté client prend en charge un sous-ensemble de Xu incluant les types de base, le contrôle de flux, les structures, les diagnostics d'emprunt et l'ordonnancement coopératif de canaux. Consultez le guide des capacités du playground pour connaître son périmètre ; le vrai multithreading, les E/S réseau, la FFI C native et l'interface bureau nécessitent le SDK natif.

### Option 2 : Installation rapide en une ligne (Recommandé)

Xu fournit des installeurs autonomes intégrant le compilateur et les sources de la bibliothèque standard, qui configurent automatiquement les variables d'environnement persistantes :

- **macOS / Linux** (une commande dans le terminal) :
  ```bash
  # Détecte l'architecture, télécharge et configure automatiquement l'environnement
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *Ou téléchargez les binaires autonomes depuis [Releases](https://github.com/xulang-org/xu/releases) :*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows** (Assistant GUI ou PowerShell) :
  - **Assistant GUI** : Téléchargez `xu-setup-windows-x64.exe` depuis [Releases](https://github.com/xulang-org/xu/releases) et double-cliquez pour lancer l'assistant graphique sans dépendance.
  - **Installeur console ARM64** : Téléchargez `xu-setup-windows-arm64.exe` depuis [Releases](https://github.com/xulang-org/xu/releases) et exécutez `.\xu-setup-windows-arm64.exe --yes` dans PowerShell.
  - Les installeurs du SDK s'exécutent par défaut au niveau de l'utilisateur courant depuis un terminal ordinaire. L'installation pour tous les utilisateurs requiert les droits administrateur.
  - **Commande PowerShell en une ligne** :
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> Ouvrez un nouveau terminal et saisissez `xu --version` pour l'exécuter depuis n'importe où.

### Option 3 : Hello World en 30 secondes

```bash
# 1. Créer le fichier source
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. Exécuter immédiatement
xu run main.xu

# 3. Compiler AOT vers un binaire natif optimisé
xu build main.xu -o myapp
./myapp
```

### Documentation

- [Guide de démarrage](https://xulang.org/fr/docs/start/)
- [Référence CLI](https://xulang.org/fr/docs/cli/), incluant l'optimisation, les tests et XACP
- [API de la bibliothèque standard et des paquets](https://xulang.org/api/)
- [Modules natifs et spans empruntés](https://xulang.org/fr/docs/native/)

La documentation et les sources de l'API sont maintenues dans [xulang-org/xulang-org](https://github.com/xulang-org/xulang-org).

---

## Applications mobiles (Phone)

Xu 0.12.4 génère des projets d'applications ARM64 pour appareils iOS, le Simulateur iOS et Android.

```sh
xu build app/ --phone --target ios-simulator-arm64 --bundle-id org.example.app -o build/ios
xu build app/ --phone --target android-arm64 --bundle-id org.example.app -o build/android
```

Chaque sortie contient un script de compilation plateforme ainsi qu'un objet d'application Xu compilé. La couche de design `#ui/phone` propose des zones tactiles, une navigation inférieure, des gabarits adaptatifs, des cartes, des lignes groupées et des feuilles inférieures. Le profil UI rend les trames Draw dans un Canvas WebView système local et prend en charge la saisie de texte via l'IME du système.
Voir [Prérequis et limites Phone](src/ui/host/phone/README.md) et la [galerie de design mobile](examples/phone_gallery/README.md).

---

## 🖥️ Développement de Noyaux d'OS et Bare-Metal

Xu prend nativement en charge les **noyaux de systèmes d'exploitation, firmwares embarqués et pilotes bare-metal**. Grâce à une architecture en couches strictement isolée, Xu préserve la **destruction déterministe Zero-GC** et **l'inférence implicite de propriété (sans annotations manuelles de lifetime)** dans le code courant, tout en confinant la manipulation matérielle aux 5 % inférieurs du code :

* **Mode Freestanding sans hôte** :
  * La directive source `$freestanding`, le manifeste projet `xu.xun` (`profile: freestanding`) ou les options CLI `--profile=freestanding` / `--no-std` coupent totalement toute dépendance aux syscalls de l'OS hôte, à l'ordonnanceur runtime et à la libc.
* **Contrats matériels strictement isolés** :
  * **Pointeurs bruts (`*raw T`)** : Le déréférencement exige des blocs explicites `unsafe { ... }` ; l'inférence de propriété et d'emprunt ignore entièrement les pointeurs bruts, préservant une fluidité totale pour le code applicatif standard ;
  * **Barrières Volatile MMIO** : Les primitives intégrées `volatile_read` et `volatile_write` empêchent l'élimination de code mort (DCE) et le hissage d'invariants de boucle (LICM) ;
  * **Contrôle précis de la disposition mémoire** : `@repr("C", align: 4096)` pour les tables de pages alignées sur 4 Ko (PML4 / Page Directory) et `@repr("C", packed)` pour les paquets réseau matériels et descripteurs sans bourrage.
* **Bibliothèque cœur purement statique (`#core`)** :
  * `#core/arch` : Instructions CPU privilégiées (`cli`, `sti`, `hlt`, `pause`, `wfi`), accès aux registres de contrôle (`read_cr2/cr3`, `write_cr3`, `invlpg`, `set_vbar`, `set_trap_vector`), descripteurs de portes d'interruption IDT (`load_idt`), remappage du PIC 8259A (`pic_remap`) et initialisation du minuteur PIT 8254 ;
  * `#core/sync` : Verrous tournants sûrs face aux interruptions `IrqSpinlock` et `Spinlock` associés aux gardes RAII `IrqGuard` et `SpinGuard` pour une **libération déterministe Zero-GC et restauration des interruptions en fin de portée** ;
  * `#core/task` : `TaskContext` multi-architecture de 192 octets aligné sur 16 octets, commutation de contexte atomique (`switch_context`), instantanés complets des registres (`TrapFrame`) et points d'entrée d'appels système (`syscall_entry`) ;
  * `#core/virtio` : Framework de pilotes VirtIO MMIO purement statique, anneaux de descripteurs VirtQueue, `VirtioBlkDriver` (périphérique bloc disque) et `VirtioNetDriver` (carte réseau virtuelle) ;
  * `#core/mem` & `#core/alloc` : Intrinsèques mémoire sans allocation (`memset`/`memcpy`/`memcmp`) et contrats d'allocateur enfichable (`GlobalAlloc`).
* **Génération instantanée de squelette noyau** :
  ```bash
  # Initialiser un nouveau projet noyau bare-metal (génère xu.xun, main.xu, linker.ld et Makefile multi-arch)
  xu init --baremetal my_os
  cd my_os

  # Compiler des images ELF de noyau bare-metal ultra-légères multi-architectures (~1,9 Ko à 2,4 Ko)
  make
  # Ou exécuter directement dans l'émulateur QEMU
  make qemu
  ```

---

## 🗺️ Feuille de Route du Projet

Le SDK publié constitue la référence de cette feuille de route. Voir [Statut et Limitations](https://xulang.org/fr/docs/status/) pour les limites d'exécution par cible.

- [x] **Auto-hébergement pur en Xu et AOT natif** : Amorçage depuis un SDK Xu publié, vérification d'un point fixe et émission directe de code machine natif et WebAssembly
- [x] **Propriété et inférence d'emprunt à la compilation** : Nettoyage déterministe des ressources ; la 0.9.4 complète la vérification pour les expressions imbriquées et les arêtes de retour de boucle
- [x] **Coroutines natives et canaux** : Ordonnancement via le mot-clé `xu` et communication typée `chan` ; validation 100/100 de la porte de concurrence `select` multitâche
- [x] **Suite cryptographique complète** : Conformité intégrale SM2/SM3/SM4/SM9 ; cadre de pile de couplage SM9 réduit de 71,5 % sans aucun avertissement de compilation
- [x] **Flux symbolique et gestion d'erreurs** : Retour `<<`, levée `>>` et gardes locales obligatoires `>>> (err) { ... }`
- [x] **Génération de code multiplateforme** : Windows / macOS / Linux, ARM64 / x64 / LoongArch64 / RISC-V, WASM et cibles bare-metal
- [x] **Support noyau d'OS et bare-metal** : Profil freestanding, sous-système statique pur `#core` (arch/mem/sync/task/alloc/virtio), spinlocks sûrs aux interruptions, commutation de contexte atomique, framework VirtIO et squelette en une commande (`xu init --baremetal`)
- [x] **Installation SDK et auto-mises à jour** : Assistant Windows, PKG macOS, installeur multiplateforme mono-fichier et `xu up/update`
- [x] **Dépendances de modules reproductibles** : `init/get/install`, MVS, verrous/vendor, proxies, compilations hors ligne/gelées et client de sommes de contrôle à clé de confiance
- [x] **LSP et intégration éditeur** : `xu-lsp` et extensions VS Code/Cursor ; diagnostics, complétion, définitions, survol, symboles, références, renommage et formatage
- [x] **Génériques et fondations d'optimisation SSA** : Monomorphisation sans la limite de quatre paramètres de type, promotion scalaire SSA, noyaux de boucle SSA ARM64 et rotation de boucles
- [x] **Diagnostics et vérification du compilateur** : Vérification MIR par passe, dumps MIR, compteurs de correspondances de motifs et contrôles de motifs nommés
- [x] **Paquets d'infrastructure** : Le module séparé packages fournit 29 extensions dont MySQL, Postgres, Redis, ClickHouse, Kafka et SQLite
- [x] **Benchmarks inter-langages traçables** : 72 charges sur six plateformes ARM64/x86-64, conservant versions de compilateurs mesurées, provenance et vérification de sortie
- [x] **Débogueur source interactif intégré** : `xu debug` pilote les points d'arrêt DWARF, piles d'appels et l'inspection typée des variables locales via LLDB/GDB avec mode lot non interactif
- [x] **Extension approfondie de l'optimiseur** : Promotion scalaire SSA approfondie avec preuves d'admission de structures, planification de tuiles inspirée de TVM, LUT-GEMM bas-bits et fusion pipelinée d'opérateurs
- [ ] **Validation runtime complète sur machines cibles** : Les portes d'installation SDK natif couvrent macOS ARM64/x64, Linux ARM64/x64 et Windows x64/ARM64. Extension continue des vérifications bibliothèque, réseau, concurrence et UI bureau sur chaque cible ; les SDK LoongArch64 et RISC-V sont compilés de façon croisée.
- [ ] **Infrastructure publique de paquets** : La vérification de sommes à clé de confiance, MVS et les clients proxy/vendor sont implémentés. Les services publics proxy/checksum et témoins indépendants nécessitent un déploiement et une validation de disponibilité distincts.

---

## 🌟 Rejoindre la Communauté et Soutenir Xu

Xu est un langage de programmation système open source tourné vers l'avenir. Si vous croyez aux **performances extrêmes Zero-GC combinées à une syntaxe moderne et ergonomique**, rejoignez-nous !

- ⭐ **Ajoutez une Star au dépôt** : Si Xu correspond à votre philosophie d'ingénierie, offrez-nous une **Star** sur [GitHub](https://github.com/xulang-org/xu) — c'est le moteur de notre développement !
- 💬 **Retours et discussions** : Des demandes de fonctionnalités ou des suggestions ? Ouvrez une discussion ou un ticket sur [GitHub Issues](https://github.com/xulang-org/xu/issues).
- 📊 **Analyses de benchmarks** : Explorez les benchmarks approfondis CPU et mémoire sur 72 charges à l'adresse [xulang.org/fr/benchmarks](https://xulang.org/fr/benchmarks/).
- 📚 **Documentation complète** : Lisez guides, spécifications syntaxiques et tutoriels sur [xulang.org](https://xulang.org/fr/).

---

## Licence

Le langage de programmation Xu est open source sous [licence MIT](LICENSE).
