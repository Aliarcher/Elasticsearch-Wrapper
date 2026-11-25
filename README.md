# eskit

لایه‌ای ساده روی `elasticsearch-py` و ماژول DSL آن (`elasticsearch.dsl`).

> پکیج جداگانه‌ی `elasticsearch-dsl` در کلاینت رسمی ادغام شده است
> (`from elasticsearch.dsl import ...`)، پس فقط پکیج `elasticsearch` لازم است.

## نصب

```bash
pip install -e ".[dev]"        # sync
pip install -e ".[async,dev]"  # sync + async
docker compose up -d           # Elasticsearch محلی (بدون امنیت، فقط توسعه)
python examples/basic.py
pytest                         # بدون نیاز به سرور
```

نسخه‌ی major کلاینت باید با سرور یکی باشد. برای سرور 8:
`pip install "elasticsearch>=8.18,<9"` و `STACK_VERSION` را هم تغییر دهید.

## اتصال به دیتابس موجود

۱) تنظیمات را با متغیر محیطی بدهید:

```bash
export ES_HOSTS=https://es.example.com:9200
export ES_API_KEY=...                  # یا ES_USERNAME و ES_PASSWORD
export ES_CA_CERTS=/path/http_ca.crt   # برای گواهی self-signed
```

فایل `.env` خودکار خوانده نمی‌شود (`set -a; . ./.env; set +a`).

۲) بررسی با خط فرمان (فقط خواندنی):

```bash
eskit check
eskit indices
eskit schema products
eskit search products --match title=laptop --eq brand=asus --size 5
eskit export products --out products.jsonl --limit 10000
```

۳) در کد:

```python
from eskit import Database, ESManager, ESSettings, QueryBuilder

with ESManager() as es:
    es.configure(ESSettings.from_env())
    db = Database(es.client())            # پیش‌فرض: read_only=True
    db.check()
    s = db.schema("products")
    repo = db.repository("products")      # alias یا الگو مثل "logs-*" هم می‌شود

    q = (QueryBuilder()
         .must(s.text("title").match("laptop"))
         .filter(s.exact("brand") == "asus"))   # خودش brand.keyword را پیدا می‌کند
    for doc in repo.search(q):
        print(doc["_id"], doc)

    for hit in repo.iter_all(q):          # همه‌ی نتایج
        ...
```

برای نوشتن: `Database(client, read_only=False)`.

### نکته‌های مهم

- `read_only` فقط جلوی اشتباه در Repository را می‌گیرد و امنیت نیست؛ `client` خام و
  `IndexManager` را محدود نمی‌کند. برای محافظت واقعی API key فقط‌خواندنی بسازید:

```json
POST /_security/api_key
{"name": "eskit-readonly",
 "role_descriptors": {"reader": {
   "cluster": ["monitor"],
   "indices": [{"names": ["products*"],
                "privileges": ["read", "view_index_metadata", "monitor"]}]}}}
```

- نسخه‌ی major کلاینت و سرور باید یکی باشد. سرور قدیمی‌تر از 8 و OpenSearch پشتیبانی نمی‌شود.
- `save` کل سند را جایگزین می‌کند. اگر مدل شما همه‌ی فیلدها را ندارد، از `update` استفاده کنید.
- `get/save/update/delete` به یک مقصد مشخص نیاز دارند، نه الگو. Data stream محدودیت نوشتن دارد.
- فیلدهای داخل nested را با `nested(path, query)` جستجو کنید.
- `export` فقط `_source` و `_id` را می‌نویسد، نه mapping و تنظیمات؛ جای snapshot/backup نیست.

## اتصال

```python
from eskit import ESManager, ESSettings

es = ESManager()
es.configure(ESSettings.from_env())                      # پیش‌فرض: localhost:9200
es.configure(ESSettings(hosts=("https://logs:9200",),
                        api_key="..."), alias="logs")    # کلاستر دوم
client = es.client()          # در اولین استفاده ساخته می‌شود
es.health()
es.close()
```

## کوئری

| کد | معادل |
|---|---|
| `F("brand") == "asus"` | term |
| `F("brand") != "asus"` | bool.must_not |
| `F("brand").isin(["a", "b"])` | terms |
| `F("price") >= 10` / `.between(10, 20)` | range |
| `F("deleted_at") == None` | فیلد وجود ندارد |
| `F("title").match("x")` / `.phrase()` / `.fuzzy()` | full text |
| `F("name").contains("ab")` | wildcard (کند روی داده‌ی زیاد) |
| `a & b`، `a \| b`، `~a` | bool |
| `multi_match(...)`، `nested(path, q)`، `Raw({...})` | سایر |

نکته‌ها:
- دور هر مقایسه پرانتز بگذارید: `(F("a") == 1) & (F("b") == 2)`.
- `and`/`or`/`not` و `1 < F("a") < 5` خطا می‌دهند.
- `==` برای فیلدهای keyword/عدد/تاریخ است؛ برای فیلد text از `match` استفاده کنید.
- `QueryBuilder` تغییرناپذیر است؛ هر متد یک نسخه‌ی جدید برمی‌گرداند.
- `None` در `must/filter/...` نادیده گرفته می‌شود؛ برای فیلتر اختیاری `when()` را ببینید.

```python
q = (QueryBuilder()
     .must(F("title").match("laptop"))
     .filter(F("price") <= 2000)
     .when(user_brand, lambda q, v: q.filter(F("brand") == v))
     .agg("by_day", Agg.date_histogram("created_at", "day"))
     .sort("-created_at")
     .paginate(1, 20))
q.to_dict()                      # بدنه‌ی خام
q.to_search(index="products")    # شیء Search از elasticsearch.dsl
```

## Repository

`get, find, get_many, exists, save, create, update, delete, search, first, count,
iter_all, bulk_save` (نسخه‌ی async: `AsyncRepository`).

- `model` می‌تواند dataclass، مدل pydantic یا خالی (dict) باشد.
- در حالت dict کلید `_id` شناسه‌ی سند است و بقیه‌ی کلیدها دست‌نخورده می‌مانند.
- در مدل‌ها فیلد `id` همان `_id` است و در `_source` ذخیره نمی‌شود. اگر داده‌ی موجود خودش فیلد `id` دارد، خواندن مقدار آن را نگه می‌دارد؛ برای نوشتن `id_field` را عوض کنید.
- اگر از `source()` برای حذف فیلدهای اجباری مدل استفاده کنید، `load` را override کنید.
- برای بیش از ۱۰٬۰۰۰ نتیجه از `iter_all` استفاده کنید.
- bulk خطای هر سند را در `BulkReport` برمی‌گرداند؛ `raise_for_errors()` آن را exception می‌کند.

## خطاها

`ESKitError` → `ESConfigError`, `ESConnectionError` (→ `ESTimeoutError`), `ESAuthError`,
`ESNotFoundError`, `ESConflictError`, `ESQueryError`, `ESBulkError`, `ESReadOnlyError`.
ترجمه‌ی خطا برای متدهای eskit است؛ فراخوانی مستقیم client یا DSL خطای اصلی را می‌دهد.

## مهاجرت mapping

```python
IndexManager(client).migrate("products", mappings=NEW_MAPPINGS)
```

index نسخه‌دار می‌سازد، reindex می‌کند و alias را اتمیک جابه‌جا می‌کند. خواندن قطع نمی‌شود،
ولی **نوشتن را در این فاصله متوقف کنید**. index قدیمی حذف نمی‌شود.
