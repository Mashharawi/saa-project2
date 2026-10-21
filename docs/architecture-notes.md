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

  ## Step 7: Processor Lambda

- Layer pillow-py312 (Pillow built inside the Lambda Python 3.12 Docker
  image so the binaries match the Lambda runtime).
- Function image-processor: Python 3.12, 1024 MB, 30 s timeout. The SQS
  event source mapping uses batch size 1; the queue's 60 s visibility
  timeout is longer than the function timeout.
- Steps: validate (size, format, pixel limits) -> resize (full 1280 px
  and 256 px thumbnail) -> watermark -> store (DynamoDB COMPLETED + SNS).
  Steps hand off through S3 and DynamoDB, so the same code can later run
  under Step Functions.
- Permanent errors (invalid file) are marked FAILED and reported by SNS
  without retrying. Transient errors are re-raised: SQS retries, and
  after 3 receives the message goes to the DLQ.
- imageId is a hash of bucket, key and S3 sequencer, so redelivered
  messages update the same DynamoDB item (idempotent).
- Outputs: images/<id>.jpg and thumbnails/<id>.jpg in the processed bucket.

## الخطوة 7: دالة Lambda للمعالجة

- الطبقة pillow-py312 (بُنيت Pillow داخل صورة Docker الخاصة بـ Lambda
  Python 3.12 لتطابق الملفات الثنائية بيئة التشغيل).
- الدالة image-processor: Python 3.12، ذاكرة 1024 ميغابايت، مهلة 30
  ثانية. ربط مصدر أحداث SQS بحجم دفعة 1؛ ومهلة رؤية الطابور (60 ثانية)
  أطول من مهلة الدالة.
- الخطوات: تحقق (الحجم والصيغة وحد البكسلات) ← تغيير الحجم (1280
  بكسل ومصغّرة 256 بكسل) ← علامة مائية ← تخزين (DynamoDB بحالة
  COMPLETED وإشعار SNS). تتسلّم الخطوات العمل عبر S3 وDynamoDB، فيمكن
  لنفس الكود أن يعمل لاحقًا تحت Step Functions.
- الأخطاء الدائمة (ملف غير صالح) تُسجَّل FAILED ويُرسل SNS إشعارها دون
  إعادة محاولة. الأخطاء العابرة تُعاد: يعيد SQS المحاولة، وبعد 3
  استقبالات تذهب الرسالة إلى الـ DLQ.
- imageId هو تجزئة للحاوية والمفتاح ومُسلسِل S3، فتحدّث الرسائل المُعاد
  تسليمها نفس عنصر DynamoDB (آمنة عند التكرار).
- المخرجات: images/<id>.jpg وthumbnails/<id>.jpg في حاوية الوجهة.


## Step 8: Step Functions Workflow

- State machine image-pipeline (Standard): Validate -> Resize ->
  Watermark -> Store -> Done. Each state invokes the image-processor
  Lambda with a "step" parameter. See infra/state-machine.json.
- Retry: ValidationError is never retried (MaxAttempts 0); any other
  error is retried twice with exponential backoff.
- Catch: any failure goes to NotifyFailure (marks the DynamoDB item
  FAILED and publishes to SNS), then a Fail state so the execution shows
  as failed in the console.
- Role image-workflow-role may only invoke the image-processor function.
  image-processor-role gained states:StartExecution on this one state
  machine.
- Setting STATE_MACHINE_ARN on the Lambda switches it from processing
  inline to starting an execution per upload. The execution name is the
  imageId, so a redelivered SQS message cannot start the work twice.
- Since the SQS message is deleted once the execution starts, retries
  and failure handling now live in Step Functions; the DLQ only catches
  failures to start an execution.
- Screenshots: docs/execution-success.png and docs/execution-failed.png

## الخطوة 8: سير عمل Step Functions

- آلة الحالات image-pipeline (Standard): Validate ← Resize ←
  Watermark ← Store ← Done. كل حالة تستدعي دالة image-processor بمعامل
  "step". انظر infra/state-machine.json.
- إعادة المحاولة: ValidationError لا يُعاد أبدًا (MaxAttempts 0)؛ وأي
  خطأ آخر يُعاد مرتين مع تباعد أسي.
- الالتقاط: أي فشل ينتقل إلى NotifyFailure (يضع عنصر DynamoDB بحالة
  FAILED وينشر إلى SNS)، ثم حالة Fail ليظهر التنفيذ فاشلًا في الكونسول.
- الدور image-workflow-role لا يستطيع إلا استدعاء دالة image-processor.
  وأضيفت لـ image-processor-role صلاحية states:StartExecution على هذه
  الآلة وحدها.
- ضبط STATE_MACHINE_ARN على الدالة يحوّلها من المعالجة المباشرة إلى بدء
  تنفيذ لكل رفع. اسم التنفيذ هو imageId، فلا يمكن لرسالة SQS مُعاد
  تسليمها أن تبدأ العمل مرتين.
- بما أن رسالة SQS تُحذف بمجرد بدء التنفيذ، فإعادة المحاولة ومعالجة
  الفشل صارتا في Step Functions؛ والـ DLQ لا يلتقط إلا فشل بدء التنفيذ.
- لقطات الشاشة: docs/execution-success.png وdocs/execution-failed.png

## Step 9: API Gateway and Pre-signed Uploads

- HTTP API image-upload-api, route POST /upload-url, Lambda proxy
  integration to image-presign. Endpoint:
  https://<apiId>.execute-api.us-east-1.amazonaws.com/upload-url
- image-presign validates the request (JSON body, contentType must be
  image/jpeg, image/png or image/webp), builds the object key itself
  (uploads/<random>-<safe name>.<ext>) and returns a SigV4 pre-signed PUT
  URL valid for 300 seconds. The signature includes the Content-Type.
- The image goes straight from the client to S3; it never passes through
  API Gateway or Lambda. The S3 event then starts the pipeline.
- The bucket stays private. The URL grants only s3:PutObject on one key,
  because the signing role (image-presign-role) can do nothing else.
- Stage throttling: 2 requests/second, burst 5. HTTP API chosen over REST
  API: simpler, about 70% cheaper, and no REST-only feature is needed.
- Limitations: a pre-signed PUT cannot enforce a maximum file size (the
  validate step rejects files over 10 MB afterwards, and the lifecycle
  rule deletes raw files after 1 day). A pre-signed POST with a
  content-length-range condition would enforce it at upload time.
- The endpoint is unauthenticated, which is acceptable for a short-lived
  lab. In production add a JWT authorizer (for example Amazon Cognito).

  ## الخطوة 9: API Gateway والرفع بروابط موقّعة مسبقًا

- HTTP API باسم image-upload-api، المسار POST /upload-url، تكامل
  Lambda proxy مع image-presign. العنوان:
  https://<apiId>.execute-api.us-east-1.amazonaws.com/upload-url
- تتحقق image-presign من الطلب (جسم JSON، وcontentType يجب أن يكون
  image/jpeg أو image/png أو image/webp)، وتبني مفتاح الكائن بنفسها
  (uploads/<عشوائي>-<اسم آمن>.<امتداد>)، وتعيد رابط PUT موقّعًا مسبقًا
  بـ SigV4 صالحًا 300 ثانية. يشمل التوقيع نوع المحتوى Content-Type.
- تنتقل الصورة مباشرة من العميل إلى S3 ولا تمر عبر API Gateway أو
  Lambda. ثم يبدأ حدث S3 خط الأنابيب.
- تبقى الحاوية خاصة. يمنح الرابط s3:PutObject على مفتاح واحد فقط،
  لأن دور التوقيع (image-presign-role) لا يستطيع غير ذلك.
- تحديد معدل المرحلة: طلبان/ثانية، دفعة 5. اخترنا HTTP API بدل REST
  API: أبسط وأرخص بنحو 70%، ولا حاجة لميزة خاصة بـ REST.
- القيود: لا يستطيع PUT الموقّع مسبقًا فرض حد أقصى لحجم الملف (تتحقق
  خطوة validate بعد ذلك وترفض ما يفوق 10 ميغابايت، وتحذف قاعدة دورة
  الحياة الملفات الخام بعد يوم). أما POST موقّع مسبقًا بشرط
  content-length-range فيفرضه وقت الرفع.
- النقطة بلا مصادقة، وهذا مقبول لمختبر قصير العمر. في الإنتاج أضف
  JWT authorizer (مثل Amazon Cognito).


  ## Step 10: CloudFront

- Distribution <distId> (<domain>.cloudfront.net) with the processed
  bucket as origin through Origin Access Control (SigV4, always sign).
  The bucket stays fully private (Block Public Access on).
- Bucket policy: only the cloudfront.amazonaws.com principal, only for
  this distribution (AWS:SourceArn condition), only s3:GetObject on
  images/* and thumbnails/*. The work/ temp files and anything else stay
  unreachable, also through CloudFront.
- Behavior: redirect HTTP to HTTPS, GET/HEAD only, compression on,
  managed CachingOptimized policy. Price class 100 (cheapest regions).
- Verified: first request x-cache Miss, second Hit; direct S3 URL and
  non-allowed paths return 403.
- Image URLs are immutable (the key contains the unique image ID), so
  long caching is safe and no invalidation is needed.
- Cost: within the CloudFront free tier (1 TB and 10M requests/month);
  no hourly charge for a distribution.
- Before deleting (teardown): a distribution must be disabled first.


## الخطوة 10: CloudFront

- التوزيع <distId> (<domain>.cloudfront.net) بحاوية الوجهة كمصدر عبر
  Origin Access Control (SigV4، توقيع دائم). تبقى الحاوية خاصة بالكامل
  (حظر الوصول العام مفعّل).
- سياسة الحاوية: مبدأ cloudfront.amazonaws.com فقط، ولهذا التوزيع فقط
  (شرط AWS:SourceArn)، وs3:GetObject فقط على images/* وthumbnails/*.
  تبقى ملفات work/ المؤقتة وكل ما عداها غير قابلة للوصول، حتى عبر
  CloudFront.
- السلوك: إعادة توجيه HTTP إلى HTTPS، GET/HEAD فقط، ضغط مفعّل، سياسة
  CachingOptimized المُدارة. فئة الأسعار 100 (الأرخص).
- التحقق: x-cache في الطلب الأول Miss وفي الثاني Hit؛ ورابط S3
  المباشر والمسارات غير المسموحة تعيد 403.
- روابط الصور ثابتة لا تتغير (المفتاح يحتوي معرّف الصورة الفريد)، فالتخزين
  الطويل آمن ولا حاجة لإبطال.
- التكلفة: ضمن الطبقة المجانية لـ CloudFront (1 تيرابايت و10 ملايين
  طلب شهريًا)؛ ولا رسوم بالساعة للتوزيع.
- قبل الحذف (التفكيك): يجب تعطيل التوزيع أولًا.