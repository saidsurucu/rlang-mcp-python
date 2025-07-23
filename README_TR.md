# Python R-Server MCP

R veri görselleştirmesi ve analizi için Python ve FastMCP ile geliştirilmiş güvenli, Docker tabanlı Model Context Protocol (MCP) sunucusu.

**Bu nedir?** Bu araç, Claude gibi LLM modelleriyle doğal dil sohbetleri yaparak R'de istatistiksel analizler gerçekleştirmenizi sağlar. Tüm R kodu güvenli Docker containerlarında çalışarak tam izolasyon ve güvenlik sağlanır.

**Temel Faydalar:**
- 🗣️ **Doğal Dil Arayüzü**: Karmaşık istatistiksel analizler için AI ile sohbet edin
- 🐳 **Güvenli Docker Çalıştırma**: Tüm R kodu izole containerlarında maksimum güvenlik için çalışır
- 📊 **Otomatik R Çalıştırma**: AI, kod yazmadan R kodunu çalıştırır ve sonuçları döndürür
- 📁 **Doğrudan Dosya Erişimi**: Yerel dizinleri monte ederek AI'ın Excel/CSV dosyalarınızla çalışmasını sağlayın
- 📈 **Yayın Kalitesinde Grafikler**: Sohbet yoluyla profesyonel ggplot2 görselleştirmeleri üretin
- ⚡ **Akıllı Önbellek**: Sonuçlar önbelleğe alınarak tekrar işlemler anında gerçekleşir
- 🔄 **Etkileşimli Analiz**: Takip soruları sorun ve analizinizi iteratif olarak geliştirin

*[English](README.md) | **Türkçe***

## Genel Bakış

Bu proje [gdbelvin'in rlang-mcp-server](https://github.com/gdbelvin/rlang-mcp-server) projesinden ilham alınmıştır ancak FastMCP framework kullanılarak tamamen Python'da yeniden yazılmıştır. Orijinal Go versiyonu temel R görselleştirme araçları sağlarken, bu Python versiyonu kapsamlı dosya yönetimi yetenekleri ve gelişmiş kullanıcı deneyimi ile işlevselliği genişletmiştir.

## Özellikler

### 🎨 **Görselleştirme ve Analiz**
- **ggplot2 Render**: ggplot2 komutları ile R kodu çalıştırarak yayın kalitesinde görselleştirmeler oluşturun
- **R Script Çalıştırma**: Akıllı dosya işleme ile herhangi bir R scripti çalıştırın ve formatlanmış çıktı alın
- **Çoklu Format**: PNG, JPEG, PDF ve SVG çıktı formatları desteği
- **Özelleştirilebilir Çıktı**: Görüntü boyutları, çözünürlük ve kalite kontrolü

### 📁 **Dosya Yönetimi** (Yeni!)
- **Dizin Montajı**: Yerel dizinleri R çalışma alanında doğrudan erişim için monte edin
- **Akıllı Dosya Keşfi**: Monte edilen dizinlerdeki dosyaları keşfetmek ve analiz etmek için R scriptleri kullanın

### 📂 **Dizin Yönetimi**
- **Dinamik Mount**: Herhangi bir yerel dizini R işlemleri için monte edin
- **Güvenli Erişim**: Absolute path kontrolü ve permission doğrulaması
- **Otomatik Workspace**: r_workspace alt dizini otomatik olarak oluşturulur

### 📦 **Paket Yönetimi**
- **Paket Kurulumu**: Versiyon kontrolü ile isteğe bağlı R paketi kurulumu
- **Paket Listeleme**: Filtreleme yetenekleri ile kurulu paketleri tarayın
- **Otomatik Bağımlılık**: Akıllı paket bağımlılık çözümü

### 🛡️ **Güvenlik ve İzolasyon**
- **Zorunlu Docker**: Tüm R kodu çalıştırma izole containerlarda
- **Hazır Image'lar**: Optimize edilmiş Docker image'ları kullanır (semoss/docker-r-packages, rocker/rstudio)
- **Path Sanitization**: Directory traversal saldırılarına karşı koruma
- **Dosya Erişim Kontrolü**: Uygun izin kontrolleri ile güvenli dosya sistemi erişimi
- **Container İzolasyonu**: Tam process ve dosya sistemi izolasyonu
- **Kalıcı Container'lar**: Daha iyi performans için oturum başına tek container

### 🚀 **Performans ve Deneyim**
- **FastMCP Framework**: Mükemmel performans ile modern Python MCP implementasyonu
- **Akıllı Önbellek**: Tekrar işlemler için bellek içi önbellek sistemi
- **Kalıcı Container'lar**: Tüm işlemler için aynı container kullanılır (başlatma yükü yok)
- **Önceden Derlenmiş Paketler**: R paketleri önceden yüklenmiş Docker image'ları kullanır
- **uv Paket Yöneticisi**: Yıldırım hızında bağımlılık yönetimi ve sanal ortamlar

## Hızlı Başlangıç

### Ön Koşullar

MCP sunucusunu kurmadan önce, sisteminize gerekli bağımlılıkları kurmanız gerekir:

#### macOS

```bash
# Homebrew kurulu değilse kurun
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# R'yi kurun
brew install r

# uv (Python paket yöneticisi) kurun
brew install uv

# Python 3.12+ kurun (kurulu değilse)
brew install python@3.12

# Docker kurun (güvenli çalıştırma için gerekli)
brew install --cask docker
```

#### Windows

```powershell
# R'yi CRAN'den kurun
# Şuradan indirip kurun: https://cran.r-project.org/bin/windows/base/

# Python 3.12+'ı python.org'dan kurun
# Şuradan indirin: https://www.python.org/downloads/windows/

# uv'yi pip ile kurun
pip install uv

# Docker Desktop kurun (güvenli çalıştırma için gerekli)
# Şuradan indirin: https://www.docker.com/products/docker-desktop
```

#### Linux (Ubuntu/Debian)

```bash
# Paket listesini güncelleyin
sudo apt update

# R'yi kurun
sudo apt install r-base r-base-dev

# Python 3.12+ kurun
sudo apt install python3.12 python3.12-venv python3-pip

# uv kurun
pip install uv

# Docker kurun (güvenli çalıştırma için gerekli)
sudo apt install docker.io
sudo systemctl start docker
sudo systemctl enable docker
```

### Kurulum

Ön koşulları kurduktan sonra MCP sunucusunu kurun:

```bash
# Yöntem 1: Doğrudan GitHub'dan kurulum (önerilen)
uvx --from git+https://github.com/saidsurucu/rlang-mcp-python rlang-mcp-python

# Yöntem 2: Clone edip yerel kurulum
git clone https://github.com/saidsurucu/rlang-mcp-python.git
cd rlang-mcp-python
uv sync

# Yöntem 3: pip ile kurulum
pip install git+https://github.com/saidsurucu/rlang-mcp-python
```

## Claude Desktop Entegrasyonu

Bu MCP sunucusunu Claude Desktop ile kullanmak için:

1. Claude Desktop'ı açın
2. **Ayarlar** > **Developer** > **Edit Config** menüsüne gidin
3. MCP sunucularınıza bu yapılandırmayı ekleyin:

```json
{
  "mcpServers": {
    "r-server-python": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/saidsurucu/rlang-mcp-python",
        "rlang-mcp-python"
      ]
    }
  }
}
```

4. Yapılandırmayı kaydedin
5. Claude Desktop'ı yeniden başlatın
6. R-Server araçları artık Claude sohbetlerinizde kullanılabilir olacak

### Sistem Gereksinimleri

- **Python 3.12+**
- **Docker** (zorunlu - tüm R çalıştırma containerlarında gerçekleşir)
- **uv** (önerilen) veya pip paket yönetimi için

**Not**: Yerel R kurulumu gerekli değil - tüm R çalıştırma Docker containerlarında gerçekleşir.

### Sunucuyu Çalıştırma

```bash
# uvx kullanarak (önerilen)
uvx --from . r-server-mcp

# Veya uv run kullanarak
uv run r-server-mcp

# Veya doğrudan Python ile
python -m r_server
```

## Mevcut Araçlar

Bu sunucu **5 temel araç** sunar:

| Araç | Açıklama | Kategori |
|------|----------|----------|
| `initialize_r_container` | Kalıcı R container'ı başlat | Container Yönetimi |
| `container_status` | Container durumu ve bilgilerini kontrol et | Container Yönetimi |
| `mount_directory` | Yerel dizini container'da /data olarak mount et | Dizin Yönetimi |
| `execute_r_script` | Akıllı dosya işleme ile R scriptleri çalıştır | Çalıştırma |
| `install_r_package` | İsteğe bağlı R paketi kur | Paket Yönetimi |

## MCP Entegrasyonu

### Claude Desktop Konfigürasyonu

`claude_desktop_config.json` dosyanıza ekleyin:

```json
{
  "mcpServers": {
    "r-server-python": {
      "command": "uvx",
      "args": [
        "--from", 
        "git+https://github.com/saidsurucu/rlang-mcp-python",
        "rlang-mcp-python"
      ]
    }
  }
}
```

## Adım Adım Kullanım İş Akışı

### Adım 1: Veri Dizininizi Monte Edin

Öncelikle Claude'a veri dizininizi monte etmesini söyleyin. Şu şekilde bir prompt kullanın:

> "/Users/you/Documents/veri-analizi dizinini R çalışma dizini olarak monte et, böylece o klasördeki dosyaları analiz edebilirsin."

Bu komut:
- Belirtilen yolu R çalışma dizini olarak ayarlar
- Otomatik olarak `r_workspace` alt dizini oluşturur
- Claude'un bu dizindeki tüm dosyaları okumasına izin verir
- Mevcut dosyalarla birlikte onay döndürür

### Adım 2: Mevcut Veriyi Keşfedin

Claude'a veri dosyalarınızı keşfetmesini isteyin:

> "Monte ettiğim dizindeki tüm dosyaları listele, özellikle Excel dosyalarını göster ve analiz için hangi veriler mevcut?"

> "satis_verileri.xlsx dosyası hakkında detaylı bilgi verir misin, hangi sayfaları içerdiğini de göster?"

### Adım 3: Verilerinizi Analiz Edin

Artık verilerinizin analizini talep edin:

> "satis_verileri.xlsx dosyasındaki satış verilerini analiz et. Veriyi yükle, özet göster ve aylara göre gruplandırılmış aylık satış toplamlarını hesapla."

> "uceyrek_rapor.xlsx dosyasındaki finansal verileri oku ve Ç1 ile Ç2 performansını karşılaştıran kapsamlı bir analiz yap."

### Adım 4: Görselleştirmeler Oluşturun

Özel görselleştirmeler talep edin:

> "satis_verileri.xlsx dosyasındaki verileri kullanarak kategoriye göre aylık satışları gösteren bir sütun grafiği oluştur. Yayın kalitesinde, uygun etiketler ve renklerle hazırla."

> "Çeyrek raporundaki verilerden çeyrek ve departmanlara göre gelir dağılımını karşılaştıran bir kutu grafiği oluştur."

### Alternatif: Dosya Yükleme Yöntemi

Bireysel dosyaları yüklemeyi tercih ederseniz:

> "Bir Excel dosyası yükleyeceğim. Lütfen kaydet ve sonra verilerdeki trendleri ve kalıpları analiz et."

### Tam İş Akışı Örneği

Claude ile tam analiz için nasıl etkileşim kurabileceğiniz:

**İlk Kurulum:**
> "/Users/you/Documents/finansal-analiz proje dizinini monte et böylece veri dosyalarıma erişebilirsin."

**Veri Keşfi:**
> "Dizinde hangi Excel dosyalarını görüyorsun? uceyrek_rapor.xlsx dosyasının yapısı hakkında bilgi verir misin?"

**Analiz Talebi:**
> "Çeyrek rapor verilerini kullanarak kapsamlı bir finansal analiz yap. Şunları görmek istiyorum:
> - Her çeyrek için özet istatistikler
> - Ç1 ve Ç2 arasında gelir karşılaştırmaları
> - Departmanlara göre performans
> - Dikkat çeken trendler veya kalıplar"

**Görselleştirme Talebi:**
> "Şunları gösteren profesyonel görselleştirmeler oluştur:
> 1. Çeyrek ve departmana göre gelir dağılımını kutu grafiği olarak
> 2. Departman performans karşılaştırmasını sütun grafiği olarak
> İş sunumuna uygun olduklarından emin ol."

**Takip Analizi:**
> "Analize dayanarak çeyrek performansımız hakkındaki temel içgörüler nelerdir? Dikkat edilmesi gereken departmanlar var mı?"

## Docker Desteği

Docker güvenlik için zorunludur. Sunucu optimize edilmiş R ortamları içeren hazır Docker image'ları kullanır:

```bash
# Docker'ın çalıştığından emin olun
docker --version

# Image'lar ilk kullanımda otomatik çekilir:
# - semoss/docker-r-packages (birincil - kapsamlı R paketleri)
# - rocker/rstudio (yedek - yaygın kullanılan R ortamı)
# - r-base:latest (son yedek - minimal R kurulumu)
```

Sunucu otomatik olarak:
1. Docker'ın çalışıp çalışmadığını kontrol eder
2. Gerekirse uygun Docker image'ını çeker
3. Oturum için kalıcı bir container oluşturur
4. Dizinleri container içinde /data olarak mount eder
5. Tüm R kodunu izole container'da çalıştırır

## Geliştirme

```bash
# Geliştirme bağımlılıklarını kur
uv sync --dev

# Testleri çalıştır
uv run pytest

# Linting çalıştır
uv run ruff check
uv run black --check .

# Tip kontrolü
uv run mypy r_server.py
```

## Sorun Giderme

### Yaygın Sorunlar

#### R bulunamıyor
```bash
# macOS: R'nin PATH'te olduğundan emin olun
echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Windows: R'yi sistem PATH'ine ekleyin
# C:\Program Files\R\R-x.x.x\bin PATH environment variable'ına ekleyin

# Linux: R development paketlerini kurun
sudo apt install r-base-dev
```

#### Python versiyon sorunları
```bash
# Python versiyonunu kontrol edin
python --version

# uv ile belirli Python versiyonu kullanın
uv python install 3.12
uv python pin 3.12
```

#### R paket kurulum hataları
```bash
# macOS: Sistem bağımlılıklarını kurun
brew install harfbuzz fribidi
brew install --cask xquartz

# Ubuntu/Debian: Sistem bağımlılıklarını kurun
sudo apt install libcurl4-openssl-dev libssl-dev libxml2-dev
sudo apt install libharfbuzz-dev libfribidi-dev

# Windows: Binary paketler kullanın
# R konsolunda:
install.packages('ggplot2', type='binary')
```

#### uv komutu bulunamıyor
```bash
# uv'yi global olarak kurun
pip install --user uv

# Veya Unix sistemlerde curl kullanın
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows: pip kullanın veya GitHub releases'den indirin
```

### Doğrulama

Kurulumunuzu test edin:

```bash
# R kurulumunu test edin
Rscript -e "R.version.string"

# R paketlerini test edin
Rscript -e "library(ggplot2); library(readxl); cat('R paketleri OK\n')"

# Python/uv test edin
uv --version
python --version

# MCP sunucusunu test edin
uvx --from git+https://github.com/saidsurucu/rlang-mcp-python rlang-mcp-python --help
```

## Orijinal ile Karşılaştırma

| Özellik | Orijinal (Go) | Bu Versiyon (Python) |
|---------|---------------|----------------------|
| Temel Araçlar | 2 | **5** |
| Dizin Montajı | ❌ | ✅ |
| Dosya Yönetimi | ❌ | ✅ |
| Paket Yönetimi | ❌ | ✅ |
| Dosya Erişim Kontrolü | ❌ | ✅ |
| Akıllı Dosya İşleme | ❌ | ✅ |
| Modern Framework | ❌ | ✅ (FastMCP) |
| Paket Yöneticisi | Go modules | **uv** |
| Test Paketi | Temel | **Kapsamlı** |

## Katkıda Bulunma

Katkılarınızı memnuniyetle karşılıyoruz! Lütfen katkı rehberlerimizi okuyun ve geliştirmeler için pull request gönderin.

## Lisans

Creative Commons Attribution-NonCommercial 4.0 International (CC-BY-NC 4.0)

Bu eser [Creative Commons Attribution-NonCommercial 4.0 International License](http://creativecommons.org/licenses/by-nc/4.0/) altında lisanslanmıştır.

## Teşekkürler

- [gdbelvin'in rlang-mcp-server](https://github.com/gdbelvin/rlang-mcp-server)'ından ilham alınmıştır
- [FastMCP](https://github.com/jlowin/fastmcp) ile geliştirilmiştir
- Hızlı Python paket yönetimi için [uv](https://github.com/astral-sh/uv) kullanılmıştır