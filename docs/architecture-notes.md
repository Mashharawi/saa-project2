# Architecture Notes: Serverless Image Processing Pipeline

Region: us-east-1

## Step 2: S3 Buckets

- saa-p2-source-121312796739: receives original uploads. Block Public
  Access on. Lifecycle: raw objects expire after 1 day.
- saa-p2-processed-121312796739: stores processed images. Block Public
  Access on (CloudFront will serve it later). Lifecycle: transition to
  Standard-IA after 30 days.
- Two separate buckets prevent a processing loop: results written to the
  source bucket would re-trigger the pipeline.
  ## الخطوة 2: حاويات S3

- saa-p2-source-121312796739: تستقبل الصور الأصلية. حظر الوصول العام
  مفعّل. دورة الحياة: تنتهي صلاحية الملفات الخام بعد يوم واحد.
- saa-p2-processed-121312796739: تخزّن الصور المعالجة. حظر الوصول
  العام مفعّل (سيخدمها CloudFront لاحقًا). دورة الحياة: الانتقال إلى
  Standard-IA بعد 30 يومًا.
- حاويتان منفصلتان تمنعان حلقة المعالجة: النتائج المكتوبة في حاوية
  المصدر ستُعيد إطلاق خط الأنابيب.