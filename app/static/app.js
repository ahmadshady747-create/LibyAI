// LibyAI Interactive WhatsApp Simulator Client

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const adminForm = document.getElementById("adminForm");
  const adminInput = document.getElementById("adminInput");
  const adminMessages = document.getElementById("adminMessages");
  const staffSenderPhone = document.getElementById("staffSenderPhone");
  const staffAuthBadge = document.getElementById("staffAuthBadge");
  const setSenderAuthorizedBtn = document.getElementById("setSenderAuthorizedBtn");
  const setSenderUnauthorizedBtn = document.getElementById("setSenderUnauthorizedBtn");

  const patientForm = document.getElementById("patientForm");
  const patientInput = document.getElementById("patientInput");
  const patientMessages = document.getElementById("patientMessages");

  const doctorsTbody = document.getElementById("doctorsTbody");
  const servicesTbody = document.getElementById("servicesTbody");
  const auditLogsContainer = document.getElementById("auditLogsContainer");
  const resetDbBtn = document.getElementById("resetDbBtn");
  const wipeDataBtn = document.getElementById("wipeDataBtn");

  const docsCountBadge = document.getElementById("docsCountBadge");
  const servicesCountBadge = document.getElementById("servicesCountBadge");
  const headerClinicTitle = document.getElementById("headerClinicTitle");
  const patientHeaderTitle = document.getElementById("patientHeaderTitle");

  // DEMO-ONLY DEFAULT: fictional placeholder staff numbers for the local
  // simulator, matching the AUTHORIZED_STAFF_PHONES default in
  // app/config.py and the demo seed. They are never active in production
  // unless staff phones are explicitly configured server-side.
  let currentAuthorizedPhones = "0920202020, 0921111111, 218912345678";

  function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    const str = String(text);
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function normalizeDigits(phone) {
    if (!phone) return "";
    const clean = phone.replace(/[٠-٩]/g, d => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
    let digits = clean.replace(/\D/g, "");
    if (digits.startsWith("00")) digits = digits.slice(2);
    if (digits.startsWith("218") && digits.length >= 9) digits = digits.slice(3);
    while (digits.startsWith("0") && digits.length > 7) digits = digits.slice(1);
    return digits;
  }

  function checkPhoneAuthorized(phone) {
    if (!phone) return false;
    const core = normalizeDigits(phone);
    if (!core) return false;

    if (["*", "all", "الكل"].includes(currentAuthorizedPhones.trim().toLowerCase())) return true;

    const tokens = currentAuthorizedPhones.split(/[,،;؛\s\n\r|/]+/).map(t => t.trim()).filter(Boolean);
    for (const token of tokens) {
      const allowedCore = normalizeDigits(token);
      if (allowedCore && core === allowedCore) return true;
    }
    return false;
  }

  function updateAuthBadge() {
    if (!staffSenderPhone || !staffAuthBadge) return;
    const phone = staffSenderPhone.value.trim();
    const isAuth = checkPhoneAuthorized(phone);
    if (isAuth) {
      staffAuthBadge.className = "auth-status-badge authorized";
      staffAuthBadge.innerText = "مصرح له ✅";
    } else {
      staffAuthBadge.className = "auth-status-badge unauthorized";
      staffAuthBadge.innerText = "غير مصرح ❌";
    }
  }

  if (staffSenderPhone) {
    staffSenderPhone.addEventListener("input", updateAuthBadge);
  }

  if (setSenderAuthorizedBtn) {
    setSenderAuthorizedBtn.addEventListener("click", () => {
      const tokens = currentAuthorizedPhones.split(/[,،;؛\s\n\r|/]+/).map(t => t.trim()).filter(Boolean);
      const firstValid = tokens.find(t => !["admin", "staff"].includes(t.toLowerCase())) || tokens[0] || "0920202020";
      staffSenderPhone.value = firstValid;
      updateAuthBadge();
    });
  }

  if (setSenderUnauthorizedBtn) {
    setSenderUnauthorizedBtn.addEventListener("click", () => {
      staffSenderPhone.value = "0929999999";
      updateAuthBadge();
    });
  }

  // Live Libya Clock (Africa/Tripoli UTC+2)
  function updateLibyaLiveClock() {
    const libyaClockText = document.getElementById("libyaClockText");
    if (!libyaClockText) return;
    try {
      const now = new Date();
      const dayFormatter = new Intl.DateTimeFormat('ar-LY', { timeZone: 'Africa/Tripoli', weekday: 'long' });
      const timeFormatter = new Intl.DateTimeFormat('ar-LY', { timeZone: 'Africa/Tripoli', hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const dayName = dayFormatter.format(now);
      const timeStr = timeFormatter.format(now);
      libyaClockText.innerText = `${dayName} (${timeStr})`;
    } catch (e) {
      const now = new Date();
      libyaClockText.innerText = now.toLocaleTimeString('ar-LY');
    }
  }
  updateLibyaLiveClock();
  setInterval(updateLibyaLiveClock, 1000);

  // Format current time HH:MM
  function getCurrentTime() {
    const now = new Date();
    return now.toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' });
  }

  // Append bubble to chat with XSS protection
  function appendBubble(container, text, type, senderName = "", isBot = false, isIgnored = false) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${type} ${isBot ? 'bot-reply' : ''} ${isIgnored ? 'ignored-bubble' : ''}`;

    let html = "";
    if (senderName) {
      html += `<span class="sender-name">${escapeHtml(senderName)}</span>`;
    }
    const safeText = escapeHtml(text).replace(/\n/g, '<br>');
    html += `<p>${safeText}</p>`;
    html += `<span class="msg-time">${getCurrentTime()}</span>`;

    bubble.innerHTML = html;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
  }

  // Global delete handlers attached to window
  window.deleteDoctor = async function(id) {
    if (confirm("هل تريد بالتأكيد حذف هذا الطبيب من النظام؟")) {
      try {
        await fetch(`/api/simulator/doctor/${id}`, { method: "DELETE" });
        await refreshSystemState();
      } catch (e) {
        console.error("Error deleting doctor:", e);
      }
    }
  };

  window.deleteService = async function(id) {
    if (confirm("هل تريد بالتأكيد حذف هذا التحليل / الخدمة من النظام؟")) {
      try {
        await fetch(`/api/simulator/service/${id}`, { method: "DELETE" });
        await refreshSystemState();
      } catch (e) {
        console.error("Error deleting service:", e);
      }
    }
  };

  // Fetch and update Live Database State
  async function refreshSystemState() {
    try {
      const res = await fetch("/api/simulator/state");
      const data = await res.json();

      // Update Clinic Title
      if (data.configs && data.configs.clinic_name) {
        if (headerClinicTitle) headerClinicTitle.innerText = `نظام الاستقبال والاستفسار الذكي لـ ${data.configs.clinic_name}`;
        if (patientHeaderTitle) patientHeaderTitle.innerText = `${data.configs.clinic_name} 🏥`;
      }

      // Sync Authorized Phones
      if (data.configs && data.configs.authorized_phones) {
        currentAuthorizedPhones = data.configs.authorized_phones;
        updateAuthBadge();
      }

      // Update Libya Time Badge
      const libyaClockText = document.getElementById("libyaClockText");
      if (libyaClockText && data.libya_time) {
        libyaClockText.innerText = `${data.libya_time.day_name} (${data.libya_time.time_arabic})`;
      }

      if (docsCountBadge) docsCountBadge.innerText = data.doctors.length;
      if (servicesCountBadge) servicesCountBadge.innerText = data.services.length;


      // 1. Render Doctors
      doctorsTbody.innerHTML = "";
      if (data.doctors.length === 0) {
        doctorsTbody.innerHTML = `<tr><td colspan="5" class="text-center" style="padding: 1.5rem; color: #94a3b8;">لا يوجد أطباء مسجلين حالياً. يمكنك استخدام زر "إدراج البيانات بـ AI" لإدخال أطباء مصحتك.</td></tr>`;
      } else {
        data.doctors.forEach(doc => {
          let badgeClass = "status-available";
          let badgeText = "متواجد اليوم ✅";

          if (doc.today_status === "apologized") {
            badgeClass = "status-apologized";
            badgeText = "معتذر اليوم ❌";
          } else if (doc.today_status === "delayed") {
            badgeClass = "status-delayed";
            badgeText = "تعديل موعد ⏰";
          } else if (doc.today_status === "left") {
            badgeClass = "status-left";
            badgeText = "غادر العيادة 🚪";
          } else if (doc.today_status === "arrived") {
            badgeClass = "status-arrived";
            badgeText = "وصل ويستقبل 🩺";
          } else if (doc.today_status === "booking_closed") {
            badgeClass = "status-closed";
            badgeText = "مكتمل العدد ⛔";
          }


          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>
              <strong>${escapeHtml(doc.name)}</strong><br>
              <small class="text-muted">${escapeHtml(doc.specialty)} - ${escapeHtml(doc.room_number || '')}</small>
            </td>
            <td><span class="status-badge ${badgeClass}">${badgeText}</span></td>
            <td><b>${escapeHtml(doc.consultation_fee)} د.ل</b></td>
            <td>
              <small>${escapeHtml(doc.regular_schedule)}</small>
              ${doc.today_note ? `<br><small style="color: #b45309; font-weight: 600;">⚠️ ${escapeHtml(doc.today_note)}</small>` : ''}
            </td>
            <td>
              <button type="button" class="delete-btn" onclick="deleteDoctor(${Number(doc.id)})" title="حذف الطبيب">🗑️</button>
            </td>
          `;
          doctorsTbody.appendChild(tr);
        });
      }

      // 2. Render Services
      servicesTbody.innerHTML = "";
      if (data.services.length === 0) {
        servicesTbody.innerHTML = `<tr><td colspan="4" class="text-center" style="padding: 1.5rem; color: #94a3b8;">لا توجد خدمات أو تحاليل مسجلة. يمكنك إدراجها بسهولة بزر "إدراج البيانات بـ AI".</td></tr>`;
      } else {
        data.services.forEach(svc => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>
              <strong>${escapeHtml(svc.name)}</strong>
              <span class="badge-role" style="font-size: 0.65rem; margin-right: 4px;">${escapeHtml(svc.category)}</span>
            </td>
            <td><b>${escapeHtml(svc.price)} د.ل</b></td>
            <td><small>${escapeHtml(svc.prep_instructions || 'لا توجد شروط خاصة')}</small></td>
            <td>
              <button type="button" class="delete-btn" onclick="deleteService(${Number(svc.id)})" title="حذف الخدمة">🗑️</button>
            </td>
          `;
          servicesTbody.appendChild(tr);
        });
      }

      // 3. Render Audit Logs
      auditLogsContainer.innerHTML = "";
      if (data.logs.length === 0) {
        auditLogsContainer.innerHTML = `<p class="empty-hint">لا توجد تعديلات مسجلة حتى الآن.</p>`;
      } else {
        data.logs.forEach(log => {
          const item = document.createElement("div");
          item.className = "log-item";
          const date = new Date(log.created_at).toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          item.innerHTML = `
            <div class="log-meta">
              <span><b>${escapeHtml(log.sender)}</b> [${escapeHtml(log.action_type)}]</span>
              <span>${escapeHtml(date)}</span>
            </div>
            <p style="margin-bottom: 2px;">💬 <i>"${escapeHtml(log.raw_message)}"</i></p>
            <p style="color: #075e54; font-weight: 600;">${escapeHtml(log.confirmation_sent)}</p>
          `;
          auditLogsContainer.appendChild(item);
        });
      }

    } catch (err) {
      console.error("Error fetching system state:", err);
    }
  }

  // Handle Admin / Staff Message Submission (Private 1:1)
  adminForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = adminInput.value.trim();
    if (!msg) return;

    const senderPhone = staffSenderPhone ? staffSenderPhone.value.trim() : "0920202020";
    const isAuth = checkPhoneAuthorized(senderPhone);
    const senderDisplay = isAuth ? `الموظف المصرح له (${senderPhone})` : `رقم غير مصرح به (${senderPhone})`;

    appendBubble(adminMessages, msg, "outgoing", senderDisplay);
    adminInput.value = "";

    const adminSubmitBtn = adminForm.querySelector('button[type="submit"]');
    if (adminSubmitBtn) adminSubmitBtn.disabled = true;

    try {
      const res = await fetch("/api/simulator/admin-message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender: senderPhone, message: msg })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      if (!data.authorized) {
        appendBubble(adminMessages, data.reply, "incoming", "نظام الأمان 🛡️", true);
      } else if (data.reply) {
        appendBubble(adminMessages, data.reply, "incoming", "المساعد الرقمي للمصحة 🤖", true);
        await refreshSystemState();
      }
    } catch (err) {
      console.error("Error posting admin message:", err);
      appendBubble(adminMessages, "⚠️ تعذر الاتصال بالخادم. يرجى التأكد من تشغيل السيرفر والمحاولة لاحقاً.", "incoming", "خطأ في النظام ⚠️", true);
    } finally {
      if (adminSubmitBtn) adminSubmitBtn.disabled = false;
    }
  });

  // Handle Patient Message Submission
  patientForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = patientInput.value.trim();
    if (!msg) return;

    appendBubble(patientMessages, msg, "outgoing", "أنت (المريض)");
    patientInput.value = "";

    // Show temporary typing indicator
    const typingBubble = document.createElement("div");
    typingBubble.className = "chat-bubble incoming";
    typingBubble.innerHTML = `<span class="sender-name">مساعد الاستقبال الرقمي</span><p><i>يكتب الآن...</i></p>`;
    patientMessages.appendChild(typingBubble);
    patientMessages.scrollTop = patientMessages.scrollHeight;

    const patientSubmitBtn = patientForm.querySelector('button[type="submit"]');
    if (patientSubmitBtn) patientSubmitBtn.disabled = true;

    try {
      const res = await fetch("/api/simulator/patient-message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender: "0910000000", message: msg })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      appendBubble(patientMessages, data.reply, "incoming", "مساعد الاستقبال الرقمي", true);
    } catch (err) {
      console.error("Error posting patient message:", err);
      appendBubble(patientMessages, "⚠️ تعذر الاتصال بالخادم أو الرد في الوقت المحدد. يرجى المحاولة بعد قليل.", "incoming", "مساعد الاستقبال الرقمي", true);
    } finally {
      typingBubble.remove();
      if (patientSubmitBtn) patientSubmitBtn.disabled = false;
    }
  });

  // Handle Quick Chips Click
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const targetInputId = chip.dataset.target;
      const text = chip.dataset.text;
      if (targetInputId && text) {
        const inputEl = document.getElementById(targetInputId);
        if (inputEl) {
          inputEl.value = text;
          inputEl.focus();
        }
      }
    });
  });

  // Handle Reset DB Button
  resetDbBtn.addEventListener("click", async () => {
    if (confirm("هل تريد استعادة البيانات الافتراضية التجريبية؟")) {
      try {
        await fetch("/api/simulator/reset", { method: "POST" });
        await refreshSystemState();
        appendBubble(adminMessages, "🔄 تم إعادة ضبط جدول الأطباء والأسعار إلى الوضع الافتراضي.", "incoming", "النظام", true);
      } catch (err) {
        console.error("Error resetting database:", err);
      }
    }
  });

  // Handle Wipe Data Button
  wipeDataBtn.addEventListener("click", async () => {
    if (confirm("هل تريد بالتأكيد مسح كافة بيانات الأطباء والخدمات والتحاليل الوهمية بالكامل للبدء على بياض؟")) {
      try {
        const res = await fetch("/api/simulator/wipe-data", { method: "POST" });
        const data = await res.json();
        await refreshSystemState();
        alert(data.message);
      } catch (err) {
        console.error("Error wiping database:", err);
      }
    }
  });

  // AI Ingest Modal Logic
  const openIngestModalBtn = document.getElementById("openIngestModalBtn");
  const closeIngestModalBtn = document.getElementById("closeIngestModalBtn");
  const cancelIngestBtn = document.getElementById("cancelIngestBtn");
  const submitIngestBtn = document.getElementById("submitIngestBtn");
  const ingestModal = document.getElementById("ingestModal");
  const ingestRawText = document.getElementById("ingestRawText");
  const ingestStatusMsg = document.getElementById("ingestStatusMsg");
  const pasteSampleDoctors = document.getElementById("pasteSampleDoctors");
  const pasteSampleServices = document.getElementById("pasteSampleServices");
  const pasteSampleTable = document.getElementById("pasteSampleTable");

  const fileDropZone = document.getElementById("fileDropZone");
  const ingestFileInput = document.getElementById("ingestFileInput");
  const browseFileLink = document.getElementById("browseFileLink");
  const selectedFileBadge = document.getElementById("selectedFileBadge");
  const selectedFileName = document.getElementById("selectedFileName");
  const selectedFileIcon = document.getElementById("selectedFileIcon");
  const removeFileBtn = document.getElementById("removeFileBtn");

  let selectedFile = null;

  function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    if (['xlsx', 'xls', 'csv'].includes(ext)) return '📊';
    if (['png', 'jpg', 'jpeg', 'webp', 'bmp'].includes(ext)) return '🖼️';
    if (ext === 'pdf') return '📄';
    return '📁';
  }

  function setSelectedFile(file) {
    if (!file) {
      selectedFile = null;
      if (ingestFileInput) ingestFileInput.value = '';
      if (selectedFileBadge) selectedFileBadge.style.display = 'none';
      return;
    }
    selectedFile = file;
    if (selectedFileName) selectedFileName.innerText = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    if (selectedFileIcon) selectedFileIcon.innerText = getFileIcon(file.name);
    if (selectedFileBadge) selectedFileBadge.style.display = 'flex';
  }

  if (fileDropZone) {
    fileDropZone.addEventListener("click", () => {
      if (ingestFileInput) ingestFileInput.click();
    });

    fileDropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      fileDropZone.classList.add("dragover");
    });

    fileDropZone.addEventListener("dragleave", () => {
      fileDropZone.classList.remove("dragover");
    });

    fileDropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      fileDropZone.classList.remove("dragover");
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        setSelectedFile(e.dataTransfer.files[0]);
      }
    });
  }

  if (browseFileLink) {
    browseFileLink.addEventListener("click", (e) => {
      e.stopPropagation();
      if (ingestFileInput) ingestFileInput.click();
    });
  }

  if (ingestFileInput) {
    ingestFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length > 0) {
        setSelectedFile(e.target.files[0]);
      }
    });
  }

  if (removeFileBtn) {
    removeFileBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setSelectedFile(null);
    });
  }

  if (openIngestModalBtn) {
    openIngestModalBtn.addEventListener("click", () => {
      ingestModal.classList.add("active");
      ingestStatusMsg.className = "ingest-status-msg";
      ingestStatusMsg.style.display = "none";
    });
  }

  const closeIngest = () => {
    ingestModal.classList.remove("active");
    setSelectedFile(null);
  };

  if (closeIngestModalBtn) closeIngestModalBtn.addEventListener("click", closeIngest);
  if (cancelIngestBtn) cancelIngestBtn.addEventListener("click", closeIngest);

  if (pasteSampleTable) {
    pasteSampleTable.addEventListener("click", () => {
      ingestRawText.value = `| اسم الطبيب | التخصص | المواعيد الأسبوعية | الكشفية | رقم العيادة |
| د. سالم الورفلي | جراحة مسالك بولية وكلى | السبت والإثنين والأربعاء (من 3:30 إلى 7:30 مساءً) | 50 د.ل | عيادة 104 |
| د. منى النور | نساء وولادة وتتبع حمل | الأحد والثلاثاء والخميس (من 10 صباحاً إلى 2 ظهراً) | 55 د.ل | عيادة 201 |
| د. هشام الفيتوري | أنف وأذن وحنجرة | يومياً عدا الجمعة (من 5 إلى 9 مساءً) | 45 د.ل | عيادة 102 |
| فحص سكر الدم العشوائي (RBS) | مختبر | متاح 24 ساعة - لا يشترط صيام | 10 د.ل | مختبر الدور الأرضي |
| فحص وظائف الكبد الشامل LFT | مختبر | متاح 24 ساعة - يفضل الصيام 6 ساعات | 45 د.ل | المختبر الرئيسي |`;
    });
  }

  if (pasteSampleDoctors) {
    pasteSampleDoctors.addEventListener("click", () => {
      ingestRawText.value = `قائمة أطباء جدد بالمصحة:
1. د. عماد المهدوي - استشاري أمراض القلب والباطنة - دوامه: السبت والإثنين والأربعاء (من 4 إلى 8:30 مساءً) - كشفية: 60 د.ل - عيادة 108 الدور الأول.
2. د. نادية الشريف - أخصائية جلدية وتجميل وعلاج بالليزر - دوامها: الأحد والثلاثاء (من 10 صباحاً إلى 2 ظهراً) - كشفية: 50 د.ل - عيادة 204.
3. د. طارق الزوي - جراحة عامة ومناظير - دوامه: الخميس والجمعة (من 5 إلى 9 مساءً) - كشفية: 45 د.ل - عيادة 106.`;
    });
  }

  if (pasteSampleServices) {
    pasteSampleServices.addEventListener("click", () => {
      ingestRawText.value = `أسعار تحاليل إضافية للمختبر:
- تحليل فيتامين د (Vitamin D): السعر 55 دينار، متاح 24 ساعة، لا يتطلب صيام.
- فحص الغدة الدرقية TSH و Free T4: السعر 40 دينار، يفضل الصيام صباحاً.
- تحليل جرثومة المعدة H.Pylori بالدم: السعر 25 دينار، متاح 24 ساعة بدون شروط.
- تخطيط صدى القلب إيكو (Echocardiogram): السعر 90 دينار، بقسم القلب بموعد مسبق.`;
    });
  }

  if (submitIngestBtn) {
    submitIngestBtn.addEventListener("click", async () => {
      const text = ingestRawText.value.trim();
      if (!text && !selectedFile) {
        alert("يرجى اختيار ملف (إكسيل أو صورة أو PDF) أو كتابة ولصق البيانات أولاً.");
        return;
      }

      submitIngestBtn.disabled = true;
      ingestStatusMsg.className = "ingest-status-msg loading";
      ingestStatusMsg.innerText = selectedFile 
        ? `⏳ جارٍ رفع وتحليل الملف "${selectedFile.name}" بواسطة الذكاء الاصطناعي (Gemini Vision)... يرجى الانتظار ثوانٍ.`
        : "⏳ جارٍ تحليل وهيكلة البيانات بواسطة الذكاء الاصطناعي (Gemini)... يرجى الانتظار ثوانٍ معدودة.";

      try {
        let res;
        if (selectedFile) {
          const formData = new FormData();
          formData.append("file", selectedFile);
          if (text) formData.append("raw_text", text);

          res = await fetch("/api/simulator/ai-ingest-file", {
            method: "POST",
            body: formData
          });
        } else {
          res = await fetch("/api/simulator/ai-ingest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ raw_text: text })
          });
        }

        const result = await res.json();

        if (result.success) {
          ingestStatusMsg.className = "ingest-status-msg success";
          ingestStatusMsg.innerText = `✅ تم بنجاح تام! استخرج الذكاء الاصطناعي ${result.doctors_count} أطباء و ${result.services_count} خدمات وتم حفظها في قاعدة البيانات فوراً.`;
          await refreshSystemState();
          setTimeout(() => {
            closeIngest();
            ingestRawText.value = "";
          }, 2500);
        } else {
          ingestStatusMsg.className = "ingest-status-msg error";
          ingestStatusMsg.innerText = `❌ خطأ: ${result.error || "تعذر إدخال البيانات"}`;
        }
      } catch (err) {
        ingestStatusMsg.className = "ingest-status-msg error";
        ingestStatusMsg.innerText = `❌ حدث خطأ في الاتصال: ${err.message}`;
      } finally {
        submitIngestBtn.disabled = false;
      }
    });
  }

  // Clinic Settings Modal Logic
  const openSettingsModalBtn = document.getElementById("openSettingsModalBtn");
  const closeSettingsModalBtn = document.getElementById("closeSettingsModalBtn");
  const cancelSettingsBtn = document.getElementById("cancelSettingsBtn");
  const saveSettingsBtn = document.getElementById("saveSettingsBtn");
  const settingsModal = document.getElementById("settingsModal");
  const settingsStatusMsg = document.getElementById("settingsStatusMsg");

  const cfgClinicName = document.getElementById("cfgClinicName");
  const cfgAddress = document.getElementById("cfgAddress");
  const cfgEmergencyPhone = document.getElementById("cfgEmergencyPhone");
  const cfgReceptionPhone = document.getElementById("cfgReceptionPhone");
  const cfgBookingPolicy = document.getElementById("cfgBookingPolicy");
  const cfgPaymentMethods = document.getElementById("cfgPaymentMethods");
  const cfgInsuranceCompanies = document.getElementById("cfgInsuranceCompanies");
  const cfgFacilitiesInfo = document.getElementById("cfgFacilitiesInfo");
  const cfgAuthorizedPhones = document.getElementById("cfgAuthorizedPhones");

  if (openSettingsModalBtn) {
    openSettingsModalBtn.addEventListener("click", async () => {
      settingsModal.classList.add("active");
      settingsStatusMsg.style.display = "none";
      try {
        const res = await fetch("/api/simulator/state");
        const data = await res.json();
        if (data.configs) {
          cfgClinicName.value = data.configs.clinic_name || "";
          cfgAddress.value = data.configs.address || "";
          cfgEmergencyPhone.value = data.configs.emergency_phone || "";
          cfgReceptionPhone.value = data.configs.reception_phone || "";
          cfgBookingPolicy.value = data.configs.booking_policy || "";
          if (cfgPaymentMethods) cfgPaymentMethods.value = data.configs.payment_methods || "";
          if (cfgInsuranceCompanies) cfgInsuranceCompanies.value = data.configs.insurance_companies || "";
          if (cfgFacilitiesInfo) cfgFacilitiesInfo.value = data.configs.facilities_info || "";
          cfgAuthorizedPhones.value = data.configs.authorized_phones || "";
        }
      } catch (e) {
        console.error(e);
      }
    });
  }

  const closeSettings = () => {
    settingsModal.classList.remove("active");
  };

  if (closeSettingsModalBtn) closeSettingsModalBtn.addEventListener("click", closeSettings);
  if (cancelSettingsBtn) cancelSettingsBtn.addEventListener("click", closeSettings);

  if (saveSettingsBtn) {
    saveSettingsBtn.addEventListener("click", async () => {
      saveSettingsBtn.disabled = true;
      settingsStatusMsg.style.display = "block";
      settingsStatusMsg.className = "ingest-status-msg loading";
      settingsStatusMsg.innerText = "⏳ جارٍ حفظ وتحديث الإعدادات...";

      try {
        const payload = {
          clinic_name: cfgClinicName.value.trim(),
          address: cfgAddress.value.trim(),
          emergency_phone: cfgEmergencyPhone.value.trim(),
          reception_phone: cfgReceptionPhone.value.trim(),
          booking_policy: cfgBookingPolicy.value.trim(),
          payment_methods: cfgPaymentMethods ? cfgPaymentMethods.value.trim() : "",
          insurance_companies: cfgInsuranceCompanies ? cfgInsuranceCompanies.value.trim() : "",
          facilities_info: cfgFacilitiesInfo ? cfgFacilitiesInfo.value.trim() : "",
          authorized_phones: cfgAuthorizedPhones.value.trim()
        };

        const res = await fetch("/api/simulator/clinic-settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const result = await res.json();

        settingsStatusMsg.style.display = "block";
        settingsStatusMsg.className = "ingest-status-msg success";
        settingsStatusMsg.innerText = "✅ " + result.message;
        await refreshSystemState();

        if (payload.authorized_phones) {
          const tokens = payload.authorized_phones.split(/[,،;؛\s\n\r|/]+/).map(t => t.trim()).filter(Boolean);
          const firstNum = tokens.find(t => !["admin", "staff"].includes(t.toLowerCase()));
          if (firstNum && staffSenderPhone) {
            staffSenderPhone.value = firstNum;
            updateAuthBadge();
          }
        }

        setTimeout(() => {
          closeSettings();
        }, 1500);
      } catch (e) {
        settingsStatusMsg.style.display = "block";
        settingsStatusMsg.className = "ingest-status-msg error";
        settingsStatusMsg.innerText = "❌ خطأ في الحفظ: " + e.message;
      } finally {
        saveSettingsBtn.disabled = false;
      }
    });
  }

  // Click outside modal to close
  if (ingestModal) {
    ingestModal.addEventListener("click", (e) => {
      if (e.target === ingestModal) closeIngest();
    });
  }
  if (settingsModal) {
    settingsModal.addEventListener("click", (e) => {
      if (e.target === settingsModal) closeSettings();
    });
  }

  // Initial load
  refreshSystemState();
});
