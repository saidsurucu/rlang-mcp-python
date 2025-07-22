# Python R-Server MCP

Bu proje, FastMCP kullanılarak Python'da geliştirilmiş kapsamlı bir R analiz sunucusudur.

## Araçlar

Bu sunucu 8 kapsamlı araç sağlar:

1. **mount_directory** - R işlemleri için yerel dizin monte etme
2. **upload_file** - R çalışma alanına dosya yükleme
3. **list_files** - Çalışma alanı dosyalarını listeleme ve filtreleme
4. **file_info** - Detaylı dosya bilgisi alma
5. **render_ggplot** - ggplot2 görselleştirmeleri oluşturma
6. **execute_r_script** - Akıllı dosya işleme ile R scriptleri çalıştırma
7. **install_r_package** - İsteğe bağlı R paketi kurma
8. **list_r_packages** - Kurulu paketleri listeleme ve arama

## Kullanım

### Temel İş Akışı

1. **Dizin Monte Et**: Veri dosyalarınızın bulunduğu dizini monte edin
2. **Dosyaları Keşfet**: Mevcut dosyaları listeleyin ve inceleyin
3. **Analiz Yap**: R scriptleri çalıştırarak veri analizi gerçekleştirin
4. **Görselleştir**: ggplot2 ile profesyonel grafikler oluşturun

### Örnek Komutlar

```
"Lütfen /Users/kullanici/Documents/veri-analizi dizinini monte et"
"Excel dosyalarını listele ve sales_data.xlsx hakkında bilgi ver"
"Satış verilerini analiz et ve aylık toplam hesapla"
"Kategoriye göre aylık satışları gösteren sütun grafiği oluştur"
```

## Özellikler

- **Docker Güvenliği**: Tüm R kodları güvenli Docker konteynerlerinde çalışır
- **Akıllı Dosya İşleme**: Eksik dosyalar otomatik olarak tespit edilir
- **Kapsamlı Format Desteği**: Excel, CSV, JSON, PDF, SVG destegi
- **Paket Yönetimi**: Otomatik R paket kurulumu ve yönetimi
- **Çoklu Dil**: İngilizce ve Türkçe dokümantasyon

## Teknik Detaylar

- **Framework**: FastMCP
- **Dil**: Python 3.12+
- **R Versiyonu**: 4.0+
- **Docker**: Zorunlu güvenlik özelliği
- **Paketler**: ggplot2, readxl, writexl, dplyr, tidyr

## Kurulum

```bash
uvx --from git+https://github.com/saidsurucu/rlang-mcp-python rlang-mcp-python
```

## Linting ve Typecheck

```bash
uv run ruff check
uv run ruff format
```