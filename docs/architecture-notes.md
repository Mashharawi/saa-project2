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

  ## Step 3: SQS and S3 Event Notification

- image-pipeline-dlq: dead-letter queue, 14-day retention.
- image-pipeline-queue: main queue, 60s visibility timeout, redrive
  policy moves a message to the DLQ after 3 failed receives.
- Queue access policy allows only s3.amazonaws.com to send messages,
  restricted by aws:SourceArn (source bucket) and aws:SourceAccount.
- Source bucket sends s3:ObjectCreated:* events to the main queue.
- The queue decouples uploads from processing: bursts are buffered,
  failures are retried, and poison messages end up in the DLQ.

  ## الخطوة 3: SQS وإشعار أحداث S3

- image-pipeline-dlq: طابور الرسائل الميتة، احتفاظ 14 يومًا.
- image-pipeline-queue: الطابور الرئيسي، مهلة رؤية 60 ثانية، وسياسة
  إعادة التوجيه تنقل الرسالة إلى الـ DLQ بعد 3 استقبالات فاشلة.
- سياسة الوصول للطابور تسمح فقط لـ s3.amazonaws.com بإرسال الرسائل،
  مقيّدة بـ aws:SourceArn (حاوية المصدر) وaws:SourceAccount.
- حاوية المصدر ترسل أحداث s3:ObjectCreated:* إلى الطابور الرئيسي.
- الطابور يفصل الرفع عن المعالجة: الدفعات تُخزَّن مؤقتًا، والفشل يُعاد
  محاولته، والرسائل السامة تنتهي في الـ DLQ.

  ## Step 4: DynamoDB

- Table image-metadata, partition key imageId (String), on-demand
  (PAY_PER_REQUEST) billing.
- One item per image: imageId, sourceKey, status, uploadTime, width,
  height (and output keys, added by the processor).
- Access pattern is a single lookup by imageId, so no sort key or
  secondary index is needed. On-demand billing means no cost when idle.
- Note for the Lambda code: "status" is a DynamoDB reserved word, so
  update expressions must alias it with ExpressionAttributeNames.

  ## الخطوة 4: DynamoDB

- الجدول image-metadata، مفتاح التقسيم imageId (نص)، فوترة on-demand
  (PAY_PER_REQUEST).
- عنصر واحد لكل صورة: imageId وsourceKey وstatus وuploadTime وwidth
  وheight (ومفاتيح المخرجات، يضيفها المعالج).
- نمط الوصول بحث واحد بـ imageId، فلا حاجة لمفتاح ترتيب أو فهرس ثانوي.
  الفوترة on-demand تعني لا تكلفة وقت الخمول.
- ملاحظة لكود Lambda: كلمة "status" كلمة محجوزة في DynamoDB، لذا
  يجب أن تستخدم تعبيرات التحديث اسمًا بديلًا عبر ExpressionAttributeNames.

  ## Step 5: SNS

- Topic image-pipeline-notifications, with an email subscription
  (confirmed).
- The processor publishes one message per job on completion or failure.
  Publishers don't know their subscribers, so email can later be
  swapped for SMS, a webhook or another queue without code changes.
- Permission to publish will be granted to the Lambda role in Step 6.

## الخطوة 5: SNS

- الموضوع image-pipeline-notifications، مع اشتراك بريد إلكتروني
  (مؤكَّد).
- ينشر المعالج رسالة واحدة لكل مهمة عند الاكتمال أو الفشل. الناشرون
  لا يعرفون مشتركيهم، فيمكن لاحقًا استبدال البريد برسالة SMS أو webhook
  أو طابور آخر دون تغيير الكود.
- سيُمنح دور Lambda صلاحية النشر في الخطوة 6.

## Step 6: IAM Roles

- image-processor-role: CloudWatch Logs (managed policy) plus an inline
  policy: s3:GetObject on the source bucket, s3:PutObject on the
  processed bucket, DynamoDB Put/Update/GetItem on image-metadata,
  sns:Publish on the notifications topic, and SQS
  Receive/Delete/GetQueueAttributes on the main queue (the Lambda SQS
  trigger polls using this role).
- image-presign-role: CloudWatch Logs plus s3:PutObject on the source
  bucket only. A pre-signed URL carries the permissions of the role that
  signed it, so this is the maximum an uploader can do.
- Two roles keep each function at least privilege. No statement uses a
  wildcard resource.
- Both trust only lambda.amazonaws.com. The Step Functions role will be
  created in Step 8.

  ## الخطوة 6: أدوار IAM

- image-processor-role: سجلات CloudWatch (سياسة مُدارة) مع سياسة
  مضمّنة: s3:GetObject على حاوية المصدر، وs3:PutObject على حاوية
  الوجهة، وPut/Update/GetItem في DynamoDB على image-metadata،
  وsns:Publish على موضوع الإشعارات، وReceive/Delete/GetQueueAttributes
  في SQS على الطابور الرئيسي (مشغّل SQS في Lambda يستطلع بهذا الدور).
- image-presign-role: سجلات CloudWatch مع s3:PutObject على حاوية
  المصدر فقط. الرابط الموقّع يحمل صلاحيات الدور الذي وقّعه، فهذا أقصى
  ما يستطيعه من يرفع.
- دوران يُبقيان كل دالة بأقل صلاحية. لا عبارة تستخدم مورد wildcard.
- كلاهما يثق بـ lambda.amazonaws.com فقط. سيُنشأ دور Step Functions
  في الخطوة 8.