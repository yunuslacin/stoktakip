# Stok Takip Uygulaması

Bu proje, çok kullanıcılı ve onay süreçli bir stok takip sistemi sunar. Uygulama stok giriş-çıkışları için FIFO yöntemini uygular, kullanıcı faaliyetlerini kayıt altına alır ve depo/proje bazlı raporlar üretir.

## Başlangıç

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Varsayılan olarak yönetici paneline `/admin/` adresinden erişebilirsiniz.

## Temel Özellikler

- **FIFO Stok Yönetimi:** Stok çıkışlarında en eski girişler öncelikli kullanılır.
- **Stok Giriş/Çıkış Kayıtları:** Depo, tedarikçi, fatura bilgisi ve birim maliyet loglanır.
- **Talep ve Onay Süreci:** Kullanıcılar stok talebi oluşturur, yöneticiler onaylar ve çıkış gerçekleştiğinde talep otomatik kapanır.
- **Manuel Düzeltmeler:** Fire ve kayıp gibi durumlar için artı/eksi stok düzeltmeleri yapılabilir.
- **Uyarılar ve Raporlar:** Kritik stok uyarıları, fiyat geçmişi ve detaylı hareket raporları sunulur.
- **Kullanıcı Yönetimi:** Yönetici ekranından kullanıcı rollerini ve hiyerarşik ilişkileri takip edebilirsiniz.

## Testler

```bash
python manage.py check
```
