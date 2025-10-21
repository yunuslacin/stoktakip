# Stok Takip Uygulaması

Flask tabanlı çok kullanıcılı stok takip sistemi. FIFO yöntemi ile stok çıkışlarını yönetir ve detaylı loglama yapar.

## Özellikler

- Kullanıcı adı/şifre ile giriş ve rol bazlı yetki yönetimi (yönetici / normal kullanıcı)
- FIFO stok çıkışı
- Stok girişlerinde depo, tedarikçi, fatura bilgisi ve birim maliyet takibi
- Stok çıkışlarında proje seçimi
- Manuel stok düzeltmeleri (fire, kayıp vb.)
- Stok talep süreci ve yönetici onay akışı
- Talep ve sipariş durum takibi
- Düşük stok uyarıları ve stok durumu raporu
- Hareket, fiyat ve aktivite log raporları

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app.py init-db
python app.py
```

Varsayılan yönetici hesabı `admin` / `admin` olarak oluşturulur.
