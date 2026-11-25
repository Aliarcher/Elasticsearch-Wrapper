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
- فیلد `id` به `_id` تبدیل می‌شود و داخل `_source` ذخیره نمی‌شود.
- اگر از `source()` برای حذف فیلدهای اجباری مدل استفاده کنید، `load` را override کنید.
- برای بیش از ۱۰٬۰۰۰ نتیجه از `iter_all` استفاده کنید.
- bulk خطای هر سند را در `BulkReport` برمی‌گرداند؛ `raise_for_errors()` آن را exception می‌کند.

## خطاها

`ESKitError` → `ESConfigError`, `ESConnectionError` (→ `ESTimeoutError`), `ESAuthError`,
`ESNotFoundError`, `ESConflictError`, `ESQueryError`, `ESBulkError`.
ترجمه‌ی خطا برای متدهای eskit است؛ فراخوانی مستقیم client یا DSL خطای اصلی را می‌دهد.

## مهاجرت mapping

```python
IndexManager(client).migrate("products", mappings=NEW_MAPPINGS)
```

index نسخه‌دار می‌سازد، reindex می‌کند و alias را اتمیک جابه‌جا می‌کند. خواندن قطع نمی‌شود،
ولی **نوشتن را در این فاصله متوقف کنید**. index قدیمی حذف نمی‌شود.
