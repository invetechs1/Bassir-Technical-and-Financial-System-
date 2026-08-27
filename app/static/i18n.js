/* عزوم — طبقة الترجمة (عربي/إنجليزي) لواجهة الاستخدام فقط.
   لا تُترجم البيانات التجارية الفعلية (نصوص العروض المولّدة، بنود قاعدة الأسعار، بيانات الشركة) —
   هذه محتوى حقيقي بالعربية ويبقى كما هو. */
const I18N = {
  app_title: { ar: "نظام عزوم — العروض الفنية والمالية", en: "AZOOM — Technical & Financial Proposals" },
  brand_tagline: { ar: "<span dir=\"ltr\">United Co.</span> — نظام العروض الفنية والمالية", en: "<span dir=\"ltr\">United Co.</span> — Proposals System" },
  lang_toggle: { ar: "English", en: "العربية" },

  nav_dashboard: { ar: "لوحة التحكم", en: "Dashboard" },
  nav_new: { ar: "عرض جديد", en: "New Proposal" },
  nav_proposals: { ar: "أرشيف العروض", en: "Proposal Archive" },
  nav_prices: { ar: "قاعدة الأسعار", en: "Price Catalog" },
  nav_library: { ar: "المكتبة الفنية", en: "Content Library" },
  nav_etimad: { ar: "منافسات اعتماد", en: "Etimad Tenders" },
  nav_forsah: { ar: "مشاريع منصة فرصة", en: "Forsah Projects" },
  nav_repo: { ar: "المستودع المعرفي", en: "Knowledge Repository" },
  nav_docs: { ar: "وثائق الشركة", en: "Company Documents" },
  nav_analytics: { ar: "التحليلات", en: "Analytics" },
  nav_settings: { ar: "الإعدادات", en: "Settings" },
  nav_logout: { ar: "تسجيل الخروج", en: "Log Out" },

  navgrp_daily: { ar: "العمل اليومي", en: "Daily Work" },
  navgrp_knowledge: { ar: "قواعد المعرفة", en: "Knowledge" },
  navgrp_opportunities: { ar: "الفرص", en: "Opportunities" },
  navgrp_company: { ar: "الشركة", en: "Company" },
  topbar_new_btn: { ar: "+ إنشاء عرض جديد", en: "+ New Proposal" },

  // لوحة التحكم
  dash_title: { ar: "لوحة التحكم", en: "Dashboard" },
  dash_sub: { ar: "نظرة عامة على نشاط العروض في عزوم", en: "Overview of AZOOM's proposal activity" },
  dash_new_btn: { ar: "+ إنشاء عرض جديد", en: "+ New Proposal" },
  dash_stat_total: { ar: "إجمالي العروض", en: "Total Proposals" },
  dash_stat_submitted: { ar: "عروض مُقدَّمة", en: "Submitted" },
  dash_stat_won: { ar: "عروض فائزة", en: "Won" },
  dash_stat_priceitems: { ar: "بند في قاعدة الأسعار", en: "Price Catalog Items" },
  dash_recent_title: { ar: "أحدث العروض", en: "Recent Proposals" },
  dash_empty: { ar: "لا توجد عروض بعد — ابدأ بإنشاء عرض جديد", en: "No proposals yet — start by creating a new one" },
  docs_alert_title: { ar: "تنبيه الوثائق النظامية", en: "Compliance Document Alert" },
  docs_alert_expired: { ar: "⛔ وثائق منتهية:", en: "⛔ Expired documents:" },
  docs_alert_expiring: { ar: "⚠️ تنتهي خلال 30 يوماً:", en: "⚠️ Expiring within 30 days:" },
  docs_alert_days: { ar: "يوماً", en: "days" },
  docs_alert_btn: { ar: "فتح وثائق الشركة", en: "Open Company Documents" },

  // جداول مشتركة
  th_ref: { ar: "رقم العرض", en: "Ref #" },
  th_project: { ar: "المشروع", en: "Project" },
  th_client: { ar: "العميل", en: "Client" },
  th_entity: { ar: "الجهة", en: "Entity" },
  th_status: { ar: "الحالة", en: "Status" },
  th_date: { ar: "التاريخ", en: "Date" },
  th_actions: { ar: "إجراءات", en: "Actions" },
  open_btn: { ar: "فتح", en: "Open" },
  delete_btn: { ar: "حذف", en: "Delete" },
  edit_btn: { ar: "تعديل", en: "Edit" },

  // عرض جديد
  new_title: { ar: "إنشاء عرض جديد", en: "Create New Proposal" },
  new_sub: { ar: "ارفع ملفات المشروع (كراسة الشروط، RFP، جداول كميات...) وسيتولى النظام إعداد العرض الفني والمالي والخطة التنفيذية", en: "Upload project files (terms of reference, RFP, BoQs...) and the system will prepare the technical & financial proposal and execution plan" },
  new_project_label: { ar: "اسم المشروع *", en: "Project Name *" },
  new_project_ph: { ar: "مثال: إنشاء وتجهيز مبنى إداري", en: "e.g. Construction & fit-out of an office building" },
  new_client_label: { ar: "العميل / الجهة *", en: "Client / Entity *" },
  new_client_ph: { ar: "مثال: أمانة منطقة الرياض", en: "e.g. Riyadh Region Municipality" },
  new_entity_label: { ar: "طبيعة المشروع", en: "Project Nature" },
  new_entity_hint: { ar: "— يجذب النظام الأسعار والعروض الفنية من نفس القطاع", en: "— the system pulls pricing and technical content from the same sector" },
  opt_gov: { ar: "جهة حكومية (منافسة عبر منصة اعتماد)", en: "Government (Etimad tender)" },
  opt_private: { ar: "قطاع خاص", en: "Private sector" },
  opt_pif: { ar: "مشاريع صندوق الاستثمارات العامة", en: "PIF projects" },
  opt_airports: { ar: "مطارات", en: "Airports" },
  new_files_label: { ar: "ملفات المشروع (PDF / Word / Excel / نص)", en: "Project files (PDF / Word / Excel / text)" },
  dropzone_text: { ar: "اسحب الملفات هنا أو اضغط للاختيار", en: "Drag files here or click to choose" },
  gen_btn: { ar: "⚡ توليد العرض الفني والمالي", en: "⚡ Generate Technical & Financial Proposal" },
  opp_btn: { ar: "🎯 تحليل فرصة الفوز أولاً", en: "🎯 Analyze Win Chance First" },
  gen_spinner_text: { ar: "جارٍ تحليل وثائق المشروع وإعداد العرض الفني والمالي والخطة التنفيذية...", en: "Analyzing project documents and preparing the technical, financial proposal and execution plan..." },
  gen_spinner_hint: { ar: "قد يستغرق التوليد بالذكاء الاصطناعي بضع دقائق للمشاريع الكبيرة", en: "AI generation may take a few minutes for large projects" },
  similar_title: { ar: "🧠 عروض سابقة مشابهة في الأرشيف — سيُبنى العرض الجديد عليها:", en: "🧠 Similar past proposals in the archive — the new proposal will build on these:" },
  similar_match: { ar: "تطابق", en: "match" },
  similar_lines: { ar: "بنداً", en: "items" },

  // أرشيف العروض
  proposals_title: { ar: "أرشيف العروض", en: "Proposal Archive" },
  proposals_sub: { ar: "جميع العروض السابقة — مرجع دائم للتسعير والمحتوى الفني", en: "All past proposals — a permanent reference for pricing and technical content" },
  proposals_empty: { ar: "لا توجد عروض بعد", en: "No proposals yet" },
  confirm_delete_proposal: { ar: "حذف هذا العرض نهائياً؟", en: "Permanently delete this proposal?" },
  msg_proposal_deleted: { ar: "تم حذف العرض", en: "Proposal deleted" },

  // عارض العرض
  st_draft: { ar: "مسودة", en: "Draft" },
  st_submitted: { ar: "مُقدَّم", en: "Submitted" },
  st_won: { ar: "فائز 🏆", en: "Won 🏆" },
  st_lost: { ar: "غير فائز", en: "Lost" },
  export_word_btn: { ar: "⬇️ تصدير Word", en: "⬇️ Export Word" },
  export_excel_btn: { ar: "⬇️ جدول الكميات Excel", en: "⬇️ Export Excel BoQ" },
  tab_tech: { ar: "العرض الفني", en: "Technical Proposal" },
  tab_fin: { ar: "العرض المالي", en: "Financial Proposal" },
  tab_plan: { ar: "الخطة التنفيذية", en: "Execution Plan" },
  team_title: { ar: "فريق العمل المقترح", en: "Proposed Project Team" },
  th_role: { ar: "الدور", en: "Role" },
  th_count: { ar: "العدد", en: "Count" },
  compliance_title: { ar: "مصفوفة الالتزام بالمتطلبات", en: "Requirements Compliance Matrix" },
  th_requirement: { ar: "المتطلب", en: "Requirement" },
  th_compliance: { ar: "الالتزام", en: "Compliance" },
  th_reference: { ar: "الموضع في العرض", en: "Reference in Proposal" },
  boq_title: { ar: "جدول الكميات والأسعار", en: "Bill of Quantities & Pricing" },
  boq_hint: { ar: "(عدّل الكميات والأسعار — يُعاد الحساب تلقائياً)", en: "(edit quantities and prices — recalculated automatically)" },
  th_num: { ar: "م", en: "#" },
  th_code: { ar: "الكود", en: "Code" },
  th_item: { ar: "البند", en: "Item" },
  th_unit: { ar: "الوحدة", en: "Unit" },
  th_qty: { ar: "الكمية", en: "Qty" },
  th_unit_price: { ar: "سعر الوحدة", en: "Unit Price" },
  th_total: { ar: "الإجمالي", en: "Total" },
  th_source: { ar: "المصدر", en: "Source" },
  add_item_btn: { ar: "+ إضافة بند", en: "+ Add Item" },
  new_item_prompt: { ar: "اسم البند الجديد:", en: "New item name:" },
  source_catalog: { ar: "قاعدة الأسعار", en: "Price Catalog" },
  source_estimate: { ar: "تقدير", en: "Estimate" },
  source_manual: { ar: "يدوي", en: "Manual" },
  source_manual_edit: { ar: "معدّل يدوياً", en: "Manually Edited" },
  fin_summary_title: { ar: "ملخص القيمة الإجمالية", en: "Total Value Summary" },
  fin_direct_cost: { ar: "التكلفة المباشرة", en: "Direct Cost" },
  fin_overhead: { ar: "المصاريف الإدارية والعمومية", en: "Overhead & G&A" },
  fin_risk: { ar: "احتياطي المخاطر", en: "Risk Reserve" },
  fin_profit: { ar: "هامش الربح", en: "Profit Margin" },
  fin_subtotal: { ar: "الإجمالي قبل الضريبة", en: "Subtotal Before VAT" },
  fin_vat: { ar: "ضريبة القيمة المضافة", en: "VAT" },
  fin_grand_total: { ar: "الإجمالي النهائي", en: "Grand Total" },
  fin_bid_bond: { ar: "الضمان الابتدائي المطلوب", en: "Required Bid Bond" },
  currency: { ar: "ر.س", en: "SAR" },
  assumptions_title: { ar: "الافتراضات والاستثناءات", en: "Assumptions & Exclusions" },
  plan_title: { ar: "الخطة التنفيذية — المدة الإجمالية", en: "Execution Plan — Total Duration" },
  weeks_label: { ar: "أسبوعاً", en: "weeks" },
  weeks_label_short: { ar: "أسابيع", en: "weeks" },
  phase_label: { ar: "المرحلة", en: "Phase" },
  timeline_title: { ar: "المخطط الزمني", en: "Timeline" },
  built_on_label: { ar: "مبني على:", en: "Built on:" },
  engine_claude: { ar: "🤖 توليد Claude AI", en: "🤖 Generated by Claude AI" },
  engine_reference: { ar: "🗄️ عرض مرجعي (محلل من عرض فعلي)", en: "🗄️ Reference proposal (analyzed from a real one)" },
  engine_template: { ar: "📋 محرك القوالب", en: "📋 Template Engine" },

  // قاعدة الأسعار
  prices_title: { ar: "قاعدة الأسعار", en: "Price Catalog" },
  prices_sub: { ar: "أسعار عزوم المعتمدة — تُستخدم تلقائياً عند بناء جداول الكميات وتُحدَّث باستمرار", en: "AZOOM's approved prices — used automatically when building BoQs and kept continuously updated" },
  export_csv_btn: { ar: "⬇️ تصدير CSV", en: "⬇️ Export CSV" },
  import_csv_label: { ar: "⬆️ استيراد CSV", en: "⬆️ Import CSV" },
  add_price_title: { ar: "إضافة / تحديث بند", en: "Add / Update Item" },
  code_label: { ar: "الكود *", en: "Code *" },
  category_label: { ar: "التصنيف *", en: "Category *" },
  category_ph: { ar: "الأعمال المدنية", en: "Civil Works" },
  unit_label: { ar: "الوحدة *", en: "Unit *" },
  unit_ph: { ar: "م2", en: "m2" },
  item_name_label: { ar: "اسم البند *", en: "Item Name *" },
  unit_price_label: { ar: "سعر الوحدة (ر.س) *", en: "Unit Price (SAR) *" },
  save_price_btn: { ar: "حفظ البند", en: "Save Item" },
  save_price_hint: { ar: "حفظ بند بكود موجود يحدّث سعره ويسجل تاريخ التغيير", en: "Saving an existing code updates its price and logs the price-history entry" },
  search_ph: { ar: "🔍 بحث بالاسم أو الكود...", en: "🔍 Search by name or code..." },
  all_categories: { ar: "كل التصنيفات", en: "All Categories" },
  th_category: { ar: "التصنيف", en: "Category" },
  th_price: { ar: "السعر (ر.س)", en: "Price (SAR)" },
  th_updated: { ar: "آخر تحديث", en: "Last Updated" },
  confirm_delete_price: { ar: "حذف هذا البند من قاعدة الأسعار؟", en: "Delete this item from the price catalog?" },
  msg_price_saved: { ar: "تم حفظ البند ✅", en: "Item saved ✅" },
  msg_csv_imported: { ar: "تم استيراد", en: "Imported" },
  msg_csv_imported_suffix: { ar: "بنداً", en: "items" },

  // المكتبة الفنية
  library_title: { ar: "المكتبة الفنية", en: "Content Library" },
  library_sub: { ar: "نصوص عزوم المعتمدة (منهجيات، خطط جودة وسلامة، تعريف الشركة...) — تُعاد صياغتها تلقائياً في كل عرض", en: "AZOOM's approved content (methodologies, QA/safety plans, company profile...) — reused and adapted automatically in every proposal" },
  add_text_title: { ar: "إضافة / تعديل نص", en: "Add / Edit Content" },
  category_label2: { ar: "التصنيف", en: "Category" },
  category_ph2: { ar: "المنهجية", en: "Methodology" },
  title_label: { ar: "العنوان *", en: "Title *" },
  body_label: { ar: "النص *", en: "Content *" },
  save_btn: { ar: "حفظ", en: "Save" },
  new_btn: { ar: "جديد", en: "New" },
  confirm_delete_lib: { ar: "حذف هذا النص من المكتبة؟", en: "Delete this entry from the library?" },
  msg_title_body_required: { ar: "العنوان والنص مطلوبان", en: "Title and content are required" },
  msg_saved: { ar: "تم الحفظ ✅", en: "Saved ✅" },

  // منافسات اعتماد
  etimad_title: { ar: "منافسات اعتماد", en: "Etimad Tenders" },
  etimad_sub: { ar: "جلب المنافسات المطروحة من منصة اعتماد وترتيبها حسب ملاءمتها لنشاط عزوم — وافق على منافسة ليحلل النظام فرصتها ويبني عرضها", en: "Fetch open tenders from the Etimad platform and rank them by fit with AZOOM's activity — approve one to have the system analyze its chances and build a proposal" },
  fetch_btn: { ar: "⬇️ جلب المنافسات من اعتماد", en: "⬇️ Fetch Tenders from Etimad" },
  session_note: { ar: "🔑 لتنزيل كراسات الشروط آلياً: شغّل من جهازك", en: "🔑 To download terms-of-reference files automatically, run this on your own machine:" },
  session_note2: { ar: "(دخول نفاذ بموافقتك من الجوال — رقم الهوية يُحفظ محلياً في إعداداتك فقط). جلب قائمة المنافسات لا يحتاج دخولاً.", en: "(Nafath login approved from your phone — your national ID is only ever stored locally in your settings). Fetching the tender list itself needs no login." },
  search_ph2: { ar: "🔍 بحث بالاسم أو الجهة...", en: "🔍 Search by name or entity..." },
  all_statuses: { ar: "كل الحالات", en: "All Statuses" },
  relevant_only_label: { ar: "الملائمة لنشاط عزوم فقط", en: "AZOOM-relevant only" },
  fetch_spinner: { ar: "جارٍ جلب المنافسات من منصة اعتماد...", en: "Fetching tenders from Etimad..." },
  th_tender: { ar: "المنافسة", en: "Tender" },
  th_agency: { ar: "الجهة", en: "Agency" },
  th_deadline: { ar: "آخر موعد للعروض", en: "Submission Deadline" },
  th_relevance: { ar: "الملاءمة لعزوم", en: "AZOOM Fit" },
  create_proposal_btn: { ar: "✨ أنشئ عرضاً", en: "✨ Create Proposal" },
  empty_tenders: { ar: "لا منافسات مخزنة — اضغط «جلب المنافسات من اعتماد» (يعمل من جهازك المتصل بالمنصة)", en: "No tenders stored — click “Fetch Tenders from Etimad” (works from a machine with access to the platform)" },
  et_status_new: { ar: "جديدة", en: "New" },
  et_status_interested: { ar: "مهتمون", en: "Interested" },
  et_status_excluded: { ar: "مستبعدة", en: "Excluded" },
  et_status_created: { ar: "أُنشئ عرض", en: "Proposal Created" },
  closest_experience: { ar: "أقرب خبرة:", en: "Closest experience:" },
  msg_status_updated: { ar: "تم تحديث الحالة", en: "Status updated" },
  msg_etimad_loaded_hint: { ar: "حُمّلت بيانات المنافسة — ارفع كراسة الشروط بعد تنزيلها من اعتماد ثم اضغط توليد", en: "Tender data loaded — upload the terms of reference after downloading it from Etimad, then click Generate" },

  // المستودع المعرفي
  repo_title: { ar: "المستودع المعرفي", en: "Knowledge Repository" },
  repo_sub: { ar: "ارفع أي عروض فنية ومالية قديمة — لعزوم أو لشركات أخرى ومنافسة — يستخرج النظام بنودها وأسعارها كأسعار سوق استرشادية، ويخزن محتواها لتطوير العروض القادمة. فعّل خيار «عرض مرجعي» (أو زر ⭐ في الجدول) ليدخل العرض ذاكرة التشابه ويُبنى عليه تلقائياً في المشاريع المشابهة. الملفات المصورة (سكان) تُقرأ بالاستخراج الضوئي OCR إن كان مثبتاً على الخادم", en: "Upload any old technical/financial proposals — AZOOM's own or competitors' — and the system extracts their items and prices as reference market rates, and stores their content to inform future proposals. Enable “Reference Proposal” (or the ⭐ button in the table) to feed the similarity engine so it's automatically drawn on for similar projects. Scanned files are read via OCR if installed on the server" },
  upload_title: { ar: "رفع ملفات للمستودع", en: "Upload Files to the Repository" },
  source_type_label: { ar: "نوع المصدر", en: "Source Type" },
  src_prev_azoom: { ar: "عرض عزوم سابق", en: "AZOOM's Past Proposal" },
  src_prev_tech: { ar: "عرض فني سابق", en: "Past Technical Proposal" },
  src_competitor: { ar: "عرض شركة منافسة", en: "Competitor's Proposal" },
  src_other_company: { ar: "عرض شركة أخرى", en: "Another Company's Proposal" },
  src_boq: { ar: "جدول كميات / كراسة شروط", en: "BoQ / Terms of Reference" },
  src_supplier: { ar: "قائمة أسعار موردين", en: "Supplier Price List" },
  sector_label: { ar: "طبيعة المشروع", en: "Project Nature" },
  sector_general: { ar: "عام — بدون قطاع محدد", en: "General — no specific sector" },
  sector_gov: { ar: "حكومي", en: "Government" },
  sector_private: { ar: "قطاع خاص", en: "Private sector" },
  sector_pif: { ar: "صندوق الاستثمارات العامة", en: "PIF" },
  sector_airports: { ar: "مطارات", en: "Airports" },
  company_label: { ar: "اسم الشركة / المصدر", en: "Company / Source Name" },
  optional_ph: { ar: "اختياري", en: "optional" },
  notes_label: { ar: "ملاحظات", en: "Notes" },
  files_label2: { ar: "الملفات (Excel / PDF / Word / نص)", en: "Files (Excel / PDF / Word / text)" },
  as_ref_label_pre: { ar: "إضافته أيضاً كـ", en: "Also add it as a" },
  as_ref_label_bold: { ar: "عرض مرجعي", en: "Reference Proposal" },
  as_ref_label_post: { ar: "في ذاكرة النظام — يستخرج العنوان والنطاق والبنود ويُبنى عليه تلقائياً عند تحليل مشاريع مشابهة", en: "in the system's memory — its title, scope, and items are extracted and it's automatically drawn on when analyzing similar projects" },
  upload_repo_btn: { ar: "📥 تحليل وتخزين في المستودع", en: "📥 Analyze & Store in Repository" },
  upload_spinner: { ar: "جارٍ تحليل الملفات واستخراج البنود والأسعار...", en: "Analyzing files and extracting items and prices..." },
  market_title: { ar: "مقارنة أسعار السوق", en: "Market Price Comparison" },
  market_sub: { ar: "— ابحث عن أي بند لمقارنة سعر عزوم بأسعار السوق المخزنة", en: "— search any item to compare AZOOM's price against stored market rates" },
  market_search_ph: { ar: "🔍 مثال: خرسانة، دهانات، تكييف...", en: "🔍 e.g. concrete, paint, HVAC..." },
  all_sectors: { ar: "كل القطاعات", en: "All Sectors" },
  repo_contents_title: { ar: "محتويات المستودع", en: "Repository Contents" },
  th_file: { ar: "الملف", en: "File" },
  th_sector: { ar: "القطاع", en: "Sector" },
  th_priced_items: { ar: "بنود مسعّرة", en: "Priced Items" },
  th_upload_date: { ar: "تاريخ الرفع", en: "Upload Date" },
  ref_btn: { ar: "⭐ مرجعي", en: "⭐ Reference" },
  ref_btn_title: { ar: "تحويله إلى عرض مرجعي يُبنى عليه في المشاريع المشابهة", en: "Convert to a reference proposal drawn on for similar projects" },
  repo_empty: { ar: "المستودع فارغ — ارفع أول ملفاتك", en: "The repository is empty — upload your first files" },
  confirm_delete_repofile: { ar: "حذف هذا الملف وبنوده من المستودع؟", en: "Delete this file and its items from the repository?" },
  msg_choose_files_first: { ar: "اختر ملفات أولاً", en: "Choose files first" },
  msg_market_count: { ar: "📊 السوق", en: "📊 Market" },
  msg_market_notes: { ar: "ملاحظة", en: "notes" },
  msg_market_min: { ar: "الأدنى", en: "Min" },
  msg_market_avg: { ar: "المتوسط", en: "Avg" },
  msg_market_max: { ar: "الأعلى", en: "Max" },
  msg_azoom_prices_match: { ar: "أسعار عزوم المعتمدة المطابقة:", en: "AZOOM's matching approved prices:" },
  msg_no_market_notes: { ar: "لا توجد ملاحظات سوق لهذا البند بعد", en: "No market notes for this item yet" },

  // تحليل فرصة الفوز
  opp_analyzing: { ar: "جارٍ تحليل فرصة الفوز...", en: "Analyzing win chance..." },
  opp_score_title: { ar: "🎯 فرصة الفوز:", en: "🎯 Win Chance:" },
  opp_weight_label: { ar: "وزن", en: "weight" },
  opp_warnings_title: { ar: "⚠️ اشتراطات تستدعي الانتباه:", en: "⚠️ Requirements that need attention:" },
  msg_enter_project_first: { ar: "أدخل اسم المشروع أولاً", en: "Enter the project name first" },
  msg_analysis_failed: { ar: "فشل التحليل:", en: "Analysis failed:" },

  // وثائق الشركة
  docs_title: { ar: "وثائق الشركة", en: "Company Documents" },
  docs_sub: { ar: "الوثائق النظامية المطلوبة للتأهل في المنافسات — النظام ينبهك قبل انتهاء صلاحية أي وثيقة بـ30 يوماً", en: "The statutory documents required to qualify in tenders — the system alerts you 30 days before any document expires" },
  add_doc_title: { ar: "إضافة / تعديل وثيقة", en: "Add / Edit Document" },
  doc_name_label: { ar: "اسم الوثيقة *", en: "Document Name *" },
  doc_name_ph: { ar: "السجل التجاري", en: "Commercial Registration" },
  doc_number_label: { ar: "رقم الوثيقة", en: "Document Number" },
  doc_issuer_label: { ar: "الجهة المصدرة", en: "Issuing Authority" },
  doc_issue_label: { ar: "تاريخ الإصدار", en: "Issue Date" },
  doc_expiry_label: { ar: "تاريخ الانتهاء", en: "Expiry Date" },
  doc_notes_label: { ar: "ملاحظات", en: "Notes" },
  save_doc_btn: { ar: "حفظ الوثيقة", en: "Save Document" },
  th_document: { ar: "الوثيقة", en: "Document" },
  th_number: { ar: "الرقم", en: "Number" },
  th_issuer: { ar: "الجهة المصدرة", en: "Issuing Authority" },
  th_expiry: { ar: "تاريخ الانتهاء", en: "Expiry Date" },
  confirm_delete_doc: { ar: "حذف هذه الوثيقة؟", en: "Delete this document?" },
  msg_doc_name_required: { ar: "اسم الوثيقة مطلوب", en: "Document name is required" },
  msg_doc_saved: { ar: "تم حفظ الوثيقة ✅", en: "Document saved ✅" },
  doc_status_expired: { ar: "منتهية ⛔", en: "Expired ⛔" },
  doc_status_expiring: { ar: "تنتهي قريباً ⚠️", en: "Expiring soon ⚠️" },
  doc_status_valid: { ar: "سارية ✅", en: "Valid ✅" },
  doc_status_missing: { ar: "غير مُدخلة", en: "Not entered" },

  // التحليلات
  analytics_title: { ar: "تحليلات الفوز والخسارة", en: "Win/Loss Analytics" },
  analytics_sub: { ar: "معايرة تسعيرك من واقع أرشيف العروض — حدّث حالات العروض (فائز/غير فائز) لتزداد دقة المؤشرات", en: "Calibrate your pricing from the proposal archive — keep proposal statuses (won/lost) updated for more accurate indicators" },
  an_win_rate: { ar: "نسبة الفوز (من العروض المحسومة)", en: "Win Rate (of decided proposals)" },
  an_won_value: { ar: "قيمة العروض الفائزة (ر.س)", en: "Won Proposals Value (SAR)" },
  an_pipeline_value: { ar: "قيمة العروض قيد الانتظار (ر.س)", en: "Pipeline Value (SAR)" },
  an_won_decided: { ar: "فائز / محسوم", en: "Won / Decided" },
  margin_calib_title: { ar: "مؤشر معايرة التسعير", en: "Pricing Calibration Indicator" },
  avg_won_margin_pre: { ar: "متوسط هامش الربح في العروض", en: "Average profit margin in" },
  avg_won_margin_word: { ar: "الفائزة", en: "won" },
  avg_lost_margin_word: { ar: "الخاسرة", en: "lost" },
  avg_margin_post: { ar: "العروض", en: "proposals" },
  entity_perf_title: { ar: "الأداء حسب نوع الجهة", en: "Performance by Entity Type" },
  th_entity_type: { ar: "نوع الجهة", en: "Entity Type" },
  th_total: { ar: "العروض", en: "Proposals" },
  th_won: { ar: "الفائزة", en: "Won" },
  th_win_rate: { ar: "نسبة الفوز", en: "Win Rate" },
  th_won_value: { ar: "قيمة الفوز (ر.س)", en: "Won Value (SAR)" },
  client_perf_title: { ar: "الأداء حسب العميل", en: "Performance by Client" },
  th_won2: { ar: "فائز", en: "Won" },
  th_lost: { ar: "غير فائز", en: "Lost" },
  no_data: { ar: "لا توجد بيانات بعد", en: "No data yet" },
  entity_gov: { ar: "جهات حكومية", en: "Government entities" },
  entity_private: { ar: "قطاع خاص", en: "Private sector" },
  entity_pif: { ar: "صندوق الاستثمارات العامة", en: "PIF" },
  entity_airports: { ar: "مطارات", en: "Airports" },

  // الإعدادات
  settings_title: { ar: "الإعدادات", en: "Settings" },
  settings_sub: { ar: "بيانات الشركة والنسب المالية المعتمدة في التسعير", en: "Company data and the financial percentages used in pricing" },
  company_data_title: { ar: "بيانات الشركة", en: "Company Data" },
  company_name_label: { ar: "اسم الشركة", en: "Company Name" },
  cr_label: { ar: "السجل التجاري", en: "Commercial Registration" },
  vat_no_label: { ar: "الرقم الضريبي", en: "VAT Number" },
  address_label: { ar: "العنوان", en: "Address" },
  phone_label: { ar: "الهاتف", en: "Phone" },
  email_label: { ar: "البريد الإلكتروني", en: "Email" },
  bank_label: { ar: "البنك", en: "Bank" },
  iban_label: { ar: "الآيبان", en: "IBAN" },
  chamber_label: { ar: "عضوية الغرفة التجارية", en: "Chamber of Commerce Membership" },
  etimad_id_label: { ar: "رقم الهوية لدخول اعتماد (نفاذ) — يُحفظ محلياً فقط", en: "National ID for Etimad (Nafath) login — stored locally only" },
  pricing_model_title: { ar: "نموذج التسعير", en: "Pricing Model" },
  overhead_label: { ar: "المصاريف الإدارية والعمومية %", en: "Overhead & G&A %" },
  risk_label: { ar: "احتياطي المخاطر %", en: "Risk Reserve %" },
  profit_label: { ar: "هامش الربح %", en: "Profit Margin %" },
  vat_label: { ar: "ضريبة القيمة المضافة %", en: "VAT %" },
  validity_label: { ar: "سريان العرض (يوم)", en: "Proposal Validity (days)" },
  bid_bond_label: { ar: "الضمان الابتدائي %", en: "Bid Bond %" },
  payment_terms_label: { ar: "شروط الدفع القياسية", en: "Standard Payment Terms" },
  save_settings_btn: { ar: "حفظ الإعدادات", en: "Save Settings" },
  change_pw_title: { ar: "🔐 تغيير كلمة المرور", en: "🔐 Change Password" },
  old_pw_label: { ar: "كلمة المرور الحالية", en: "Current Password" },
  new_pw_label: { ar: "كلمة المرور الجديدة (8 أحرف فأكثر)", en: "New Password (8+ characters)" },
  change_pw_btn: { ar: "تغيير كلمة المرور", en: "Change Password" },
  msg_enter_pw_both: { ar: "أدخل كلمة المرور الحالية والجديدة", en: "Enter both the current and new password" },
  msg_pw_changed: { ar: "تم تغيير كلمة المرور ✅", en: "Password changed ✅" },
  msg_fill_required: { ar: "أكمل الحقول المطلوبة", en: "Fill in the required fields" },
  msg_settings_saved: { ar: "تم حفظ الإعدادات ✅", en: "Settings saved ✅" },

  // عام
  ai_engine_badge_on: { ar: "🤖 محرك التوليد: Claude AI", en: "🤖 Generation Engine: Claude AI" },
  ai_engine_badge_off: { ar: "📋 محرك التوليد: القوالب الذكية<br>أضف ANTHROPIC_API_KEY لتفعيل الذكاء الاصطناعي", en: "📋 Generation Engine: Smart Templates<br>Add ANTHROPIC_API_KEY to enable AI" },
  ai_engine_hint_on: { ar: "سيُولَّد العرض بالذكاء الاصطناعي (Claude) استناداً لوثائق المشروع وقاعدة أسعار عزوم", en: "The proposal will be generated by Claude AI based on the project documents and AZOOM's price catalog" },
  ai_engine_hint_off: { ar: "التوليد بمحرك القوالب الذكية — أضف مفتاح API في ملف ‎.env لتفعيل Claude", en: "Generated by the smart template engine — add an API key in the .env file to enable Claude" },
  msg_enter_project_client: { ar: "أدخل اسم المشروع والعميل", en: "Enter the project name and client" },
  msg_gen_failed: { ar: "فشل التوليد:", en: "Generation failed:" },
  msg_proposal_created: { ar: "تم إنشاء العرض", en: "Proposal" },
  msg_proposal_created_suffix: { ar: "بنجاح ✅", en: "created successfully ✅" },
  msg_upload_failed: { ar: "فشل الرفع:", en: "Upload failed:" },
  msg_fetch_failed: { ar: "فشل الجلب:", en: "Fetch failed:" },
  msg_session_expired: { ar: "انتهت الجلسة", en: "Session expired" },
  msg_upload_stored: { ar: "✅ خُزّن", en: "✅ Stored" },
  msg_upload_files_word: { ar: "ملفاً واستُخرج", en: "file(s), extracted" },
  msg_upload_items_word: { ar: "بنداً مسعّراً", en: "priced item(s)" },
  msg_upload_refs_word: { ar: "وأُنشئ", en: "and created" },
  msg_upload_refs_word2: { ar: "عرضاً مرجعياً", en: "reference proposal(s)" },
  msg_ref_created: { ar: "⭐ أُنشئ العرض المرجعي", en: "⭐ Reference proposal created:" },
  msg_ref_built_on: { ar: "سيُبنى عليه في المشاريع المشابهة", en: "will be drawn on for similar projects" },
  msg_fetch_ok: { ar: "✅ فُحصت", en: "✅ Scanned" },
  msg_fetch_ok_mid: { ar: "منافسة وأُضيفت", en: "tender(s), added" },
  msg_fetch_ok_end: { ar: "جديدة", en: "new" },
};

const LANG_KEY = "azoom_lang";
function getLang() { return localStorage.getItem(LANG_KEY) || "ar"; }
function setLang(lang) { localStorage.setItem(LANG_KEY, lang); }

function t(key) {
  const entry = I18N[key];
  if (!entry) return key;
  return entry[getLang()] ?? entry.ar;
}

function applyDir() {
  const lang = getLang();
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
}

function applyTranslations() {
  applyDir();
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    if (el.children.length) {
      // استبدال النص فقط مع إبقاء الأبناء (مثل عدادات القائمة)
      const first = el.firstChild;
      if (first && first.nodeType === Node.TEXT_NODE) first.nodeValue = t(key);
      else el.insertBefore(document.createTextNode(t(key)), el.firstChild);
    } else {
      el.textContent = t(key);
    }
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPh);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  const langBtn = document.getElementById("langToggle");
  if (langBtn) langBtn.textContent = getLang() === "ar" ? "EN" : "AR";
  document.title = t("app_title");
}

function toggleLang() {
  setLang(getLang() === "ar" ? "en" : "ar");
  applyTranslations();
  if (typeof onLangChange === "function") onLangChange();
}

applyDir();
document.addEventListener("DOMContentLoaded", applyTranslations);
