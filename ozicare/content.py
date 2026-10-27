"""
Approved patient-facing wording, English and Arabic.

This is the "approved knowledge" the spec requires: every critical path (first
contact, explanation, booking, escalation, decline) is sent from here verbatim.
The LLM is only used to answer free-text questions, and it is grounded on this
file plus the case summary — never on its own medical knowledge.

Clinical review note: wording is deliberately generic ("needs a follow-up
check", never "you have X"). A programme deploying this should have its own
clinician sign off each SCREENING entry before go-live.
"""

from __future__ import annotations

LANGS = ("en", "ar")

SCREENING: dict[str, dict[str, dict]] = {
    "blood_pressure": {
        "en": {
            "name": "blood pressure screening",
            "explain": (
                "Your blood pressure reading at the screening was higher than the healthy range. "
                "One reading is not a diagnosis — blood pressure can be raised by stress, rushing or caffeine. "
                "But it does mean a health worker should check it again and talk with you about it."
            ),
            "next_steps": [
                "Visit a clinic for a repeat blood pressure check.",
                "A nurse or doctor will decide whether you need more tests or treatment.",
                "Keep taking any medicine you already take unless a clinician tells you otherwise.",
            ],
            "bring": "Your ID, this message, and a list of any medicines you take.",
            "warning": "severe headache, chest pain, difficulty breathing, weakness on one side, or confusion",
        },
        "ar": {
            "name": "فحص ضغط الدم",
            "explain": (
                "كانت قراءة ضغط الدم لديك في الفحص أعلى من المعدل الطبيعي. "
                "قراءة واحدة لا تعني تشخيصاً، فقد يرتفع الضغط بسبب التوتر أو العجلة أو الكافيين. "
                "لكن من المهم أن يعيد أحد العاملين الصحيين قياسه ويتحدث معك بشأنه."
            ),
            "next_steps": [
                "زيارة العيادة لإعادة قياس ضغط الدم.",
                "سيقرر الممرض أو الطبيب إن كنت بحاجة إلى فحوصات أو علاج إضافي.",
                "استمر في تناول أي دواء تتناوله حالياً ما لم يطلب منك الطبيب غير ذلك.",
            ],
            "bring": "هويتك، وهذه الرسالة، وقائمة بأي أدوية تتناولها.",
            "warning": "صداع شديد، أو ألم في الصدر، أو صعوبة في التنفس، أو ضعف في جانب واحد من الجسم، أو ارتباك",
        },
    },
    "diabetes": {
        "en": {
            "name": "blood sugar (diabetes) screening",
            "explain": (
                "Your blood sugar result at the screening was outside the healthy range. "
                "A screening test is not a diagnosis. A follow-up test at a clinic is needed "
                "to confirm the result and decide what, if anything, should be done."
            ),
            "next_steps": [
                "Visit a clinic for a confirmatory blood test.",
                "You may be asked not to eat for 8 hours before the test — the clinic will tell you.",
                "A clinician will explain the result and any next steps.",
            ],
            "bring": "Your ID, this message, and a list of any medicines you take.",
            "warning": "extreme thirst with confusion, vomiting that will not stop, fainting, or very fast breathing",
        },
        "ar": {
            "name": "فحص سكر الدم (السكري)",
            "explain": (
                "كانت نتيجة سكر الدم لديك في الفحص خارج المعدل الطبيعي. "
                "فحص التحري لا يعني تشخيصاً. يلزم إجراء فحص متابعة في العيادة "
                "لتأكيد النتيجة وتحديد ما إذا كان هناك أي إجراء مطلوب."
            ),
            "next_steps": [
                "زيارة العيادة لإجراء فحص دم تأكيدي.",
                "قد يُطلب منك الصيام ٨ ساعات قبل الفحص، وستخبرك العيادة بذلك.",
                "سيشرح لك الطبيب النتيجة وأي خطوات تالية.",
            ],
            "bring": "هويتك، وهذه الرسالة، وقائمة بأي أدوية تتناولها.",
            "warning": "عطش شديد مع ارتباك، أو قيء مستمر، أو إغماء، أو تنفس سريع جداً",
        },
    },
    "cervical": {
        "en": {
            "name": "cervical screening",
            "explain": (
                "Your cervical screening found changes that need a closer look. "
                "This is common and in most cases it is not cancer. "
                "A follow-up examination lets a clinician check the cells and treat early if needed."
            ),
            "next_steps": [
                "Book a follow-up examination at a women's health or gynaecology clinic.",
                "The clinician will explain the examination before it starts.",
                "Early follow-up is what makes cervical screening work.",
            ],
            "bring": "Your ID and this message.",
            "warning": "heavy bleeding or severe pain in your lower belly",
        },
        "ar": {
            "name": "فحص عنق الرحم",
            "explain": (
                "أظهر فحص عنق الرحم لديك تغيرات تحتاج إلى فحص أدق. "
                "هذا أمر شائع، وفي معظم الحالات لا يكون سرطاناً. "
                "يتيح فحص المتابعة للطبيب التحقق من الخلايا وعلاجها مبكراً إذا لزم الأمر."
            ),
            "next_steps": [
                "حجز موعد فحص متابعة في عيادة صحة المرأة أو النساء والولادة.",
                "سيشرح لك الطبيب الفحص قبل البدء به.",
                "المتابعة المبكرة هي ما يجعل فحص عنق الرحم فعالاً.",
            ],
            "bring": "هويتك وهذه الرسالة.",
            "warning": "نزيف شديد أو ألم شديد في أسفل البطن",
        },
    },
    "general_abnormal": {
        "en": {
            "name": "health screening",
            "explain": (
                "One of your health screening results was outside the expected range. "
                "A screening result is not a diagnosis. It means a clinician should review it "
                "with you and decide whether any further tests are needed."
            ),
            "next_steps": [
                "Visit a clinic so a clinician can review your result.",
                "They may repeat the test or arrange further checks.",
                "Ask the clinician any questions you have about the result.",
            ],
            "bring": "Your ID, this message, and a list of any medicines you take.",
            "warning": "chest pain, difficulty breathing, fainting, or severe pain",
        },
        "ar": {
            "name": "الفحص الصحي",
            "explain": (
                "كانت إحدى نتائج فحصك الصحي خارج المعدل المتوقع. "
                "نتيجة الفحص لا تعني تشخيصاً، بل تعني أن على الطبيب مراجعتها معك "
                "وتحديد ما إذا كانت هناك حاجة لفحوصات إضافية."
            ),
            "next_steps": [
                "زيارة العيادة ليراجع الطبيب نتيجتك.",
                "قد يعيد الفحص أو يطلب فحوصات أخرى.",
                "اسأل الطبيب عن أي استفسار لديك بخصوص النتيجة.",
            ],
            "bring": "هويتك، وهذه الرسالة، وقائمة بأي أدوية تتناولها.",
            "warning": "ألم في الصدر، أو صعوبة في التنفس، أو إغماء، أو ألم شديد",
        },
    },
}

SCREENING_TYPES = tuple(SCREENING)

# Patient-facing strings. {placeholders} are filled by t().
TEXT: dict[str, dict[str, str]] = {
    "first_contact": {
        "en": (
            "Hello {first_name}, this is {org}.\n\n"
            "You have a follow-up from your recent health screening that needs your attention.\n\n"
            "Reply:\n1 — Explain my result\n2 — Help me book\n3 — Call me\n\n"
            "للعربية، أرسل: عربي"
        ),
        "ar": (
            "مرحباً {first_name}، معك {org}.\n\n"
            "لديك متابعة لفحصك الصحي الأخير تحتاج إلى اهتمامك.\n\n"
            "أرسل:\n١ — اشرح نتيجتي\n٢ — ساعدني في الحجز\n٣ — اتصل بي\n\n"
            "For English, reply: English"
        ),
    },
    "urgent_suffix": {
        "en": "\n\nThis follow-up is important. Please reply today.",
        "ar": "\n\nهذه المتابعة مهمة. يرجى الرد اليوم.",
    },
    "confirm_identity": {
        "en": (
            "To protect your privacy, please confirm you are {first_name} before we share any details.\n\n"
            "Reply YES if this is you, or NO if it is not."
        ),
        "ar": (
            "حفاظاً على خصوصيتك، يرجى تأكيد أنك {first_name} قبل أن نشارك أي تفاصيل.\n\n"
            "أرسل نعم إذا كنت أنت، أو لا إذا لم تكن."
        ),
    },
    "wrong_person": {
        "en": "Thank you for telling us. We will not message this number again about this. Sorry for the trouble.",
        "ar": "شكراً لإبلاغنا. لن نراسل هذا الرقم مرة أخرى بخصوص هذا الأمر. نعتذر عن الإزعاج.",
    },
    "menu": {
        "en": "What would you like to do next?\n1 — Explain my result\n2 — Help me book\n3 — Call me\n4 — I don't want follow-up",
        "ar": "ماذا تريد أن تفعل الآن؟\n١ — اشرح نتيجتي\n٢ — ساعدني في الحجز\n٣ — اتصل بي\n٤ — لا أريد المتابعة",
    },
    "explain_header": {"en": "About your {screening}:", "ar": "بخصوص {screening}:"},
    "next_steps_header": {"en": "What to do next:", "ar": "الخطوات التالية:"},
    "not_diagnosis": {
        "en": "This message is guidance, not a diagnosis. A clinician will review your result with you.",
        "ar": "هذه الرسالة إرشادية وليست تشخيصاً. سيراجع الطبيب نتيجتك معك.",
    },
    "warning": {
        "en": "If you have {warning}, go to the nearest emergency department or call emergency services now.",
        "ar": "إذا كان لديك {warning}، توجه إلى أقرب قسم طوارئ أو اتصل بالإسعاف فوراً.",
    },
    "slots_intro": {
        "en": "Here are the next available follow-up appointments at {clinic}. Reply with the number of the one that suits you:",
        "ar": "هذه أقرب مواعيد المتابعة المتاحة في {clinic}. أرسل رقم الموعد المناسب لك:",
    },
    "slots_other": {
        "en": "None of these work? Reply HUMAN and someone from our team will contact you to find a time.",
        "ar": "لا يناسبك أي منها؟ أرسل موظف وسيتواصل معك أحد أعضاء فريقنا لإيجاد وقت مناسب.",
    },
    "booked": {
        "en": "You're booked ✅\n\n{slot}\n{clinic}\n{address}\n\nPlease bring: {bring}\n\nWe will remind you the day before. Reply 3 if you need to change it.",
        "ar": "تم الحجز ✅\n\n{slot}\n{clinic}\n{address}\n\nيرجى إحضار: {bring}\n\nسنذكرك قبل الموعد بيوم. أرسل ٣ إذا احتجت إلى تغييره.",
    },
    "call_me": {
        "en": "Tap the button below to talk to our assistant now, any time. A staff member can also call you if you prefer — just reply HUMAN.",
        "ar": "اضغط على الزر أدناه للتحدث مع مساعدنا الآن في أي وقت. يمكن أيضاً لأحد الموظفين الاتصال بك إن أردت — أرسل: موظف",
    },
    "call_button": {"en": "Talk to us", "ar": "تحدث معنا"},
    "human_requested": {
        "en": "Thank you. A member of our care team will contact you soon. If this is an emergency, call emergency services now.",
        "ar": "شكراً لك. سيتواصل معك أحد أعضاء فريق الرعاية قريباً. إذا كانت حالة طارئة، اتصل بالإسعاف فوراً.",
    },
    "emergency": {
        "en": (
            "What you describe may need urgent care. Please go to the nearest emergency department "
            "or call emergency services now. We have also alerted our care team."
        ),
        "ar": (
            "ما تصفه قد يحتاج إلى رعاية عاجلة. يرجى التوجه إلى أقرب قسم طوارئ "
            "أو الاتصال بالإسعاف فوراً. لقد أبلغنا فريق الرعاية لدينا أيضاً."
        ),
    },
    "decline_confirm": {
        "en": (
            "We respect your choice. Before you decide: follow-up is how problems are caught early, "
            "and the visit is usually short.\n\nReply 4 again to confirm you don't want follow-up, "
            "or 1 to hear more about your result."
        ),
        "ar": (
            "نحترم قرارك. قبل أن تقرر: المتابعة هي الطريقة لاكتشاف المشكلات مبكراً، "
            "والزيارة عادة قصيرة.\n\nأرسل ٤ مرة أخرى لتأكيد أنك لا تريد المتابعة، "
            "أو ١ لمعرفة المزيد عن نتيجتك."
        ),
    },
    "declined": {
        "en": "Understood. We have recorded that you do not want follow-up. If you change your mind, message us here at any time.",
        "ar": "مفهوم. لقد سجلنا أنك لا تريد المتابعة. إذا غيرت رأيك، راسلنا هنا في أي وقت.",
    },
    "reminder": {
        "en": "Hello {first_name}, a reminder from {org}: your screening follow-up still needs your attention.\n\nReply 1 to explain, 2 to book, or 3 for a call.",
        "ar": "مرحباً {first_name}، تذكير من {org}: ما زالت متابعة فحصك تحتاج إلى اهتمامك.\n\nأرسل ١ للشرح، أو ٢ للحجز، أو ٣ لنتصل بك.",
    },
    "appointment_reminder": {
        "en": "Reminder: your follow-up appointment is {slot} at {clinic}. Reply 3 if you need to change it.",
        "ar": "تذكير: موعد المتابعة الخاص بك {slot} في {clinic}. أرسل ٣ إذا احتجت إلى تغييره.",
    },
    "fallback": {
        "en": "I'm not able to answer that here, but a member of our care team can. Reply HUMAN to be contacted, or choose an option:\n1 — Explain my result\n2 — Help me book\n3 — Call me",
        "ar": "لا أستطيع الإجابة عن ذلك هنا، لكن يمكن لأحد أعضاء فريق الرعاية مساعدتك. أرسل موظف ليتم التواصل معك، أو اختر:\n١ — اشرح نتيجتي\n٢ — ساعدني في الحجز\n٣ — اتصل بي",
    },
    "no_case": {
        "en": "Hello, this is {org}. We don't have an open screening follow-up for this number. If you think this is a mistake, please contact the clinic where you were screened.",
        "ar": "مرحباً، معك {org}. لا توجد لدينا متابعة فحص مفتوحة لهذا الرقم. إذا كنت تعتقد أن هذا خطأ، يرجى التواصل مع العيادة التي أجريت فيها الفحص.",
    },
    "closed_thanks": {
        "en": "Thank you, {first_name}. Your follow-up is complete. Look after yourself, and message us here if you need anything.",
        "ar": "شكراً لك يا {first_name}. اكتملت متابعتك. اعتنِ بنفسك، وراسلنا هنا إذا احتجت أي شيء.",
    },
    "language_set": {
        "en": "Okay, I'll continue in English.",
        "ar": "حسناً، سأكمل باللغة العربية.",
    },
}

BUTTONS = {
    "explain": {"en": "Explain my result", "ar": "اشرح نتيجتي"},
    "book": {"en": "Help me book", "ar": "ساعدني في الحجز"},
    "call": {"en": "Call me", "ar": "اتصل بي"},
}

# Demo clinic. A pilot replaces this with a real directory keyed by location.
CLINIC = {
    "en": {"name": "Riverside Primary Health Centre", "address": "12 Riverside Road — map: https://maps.google.com/?q=Riverside+Primary+Health+Centre"},
    "ar": {"name": "مركز ريفرسايد للرعاية الصحية الأولية", "address": "١٢ طريق ريفرسايد — الخريطة: https://maps.google.com/?q=Riverside+Primary+Health+Centre"},
}


def t(key: str, lang: str, **kw) -> str:
    lang = lang if lang in LANGS else "en"
    return TEXT[key][lang].format(**kw)


def screening(screening_type: str, lang: str) -> dict:
    entry = SCREENING.get(screening_type) or SCREENING["general_abnormal"]
    return entry[lang if lang in LANGS else "en"]


def explanation(screening_type: str, lang: str, result_summary: str = "") -> str:
    """The full approved explanation sent for option 1."""
    s = screening(screening_type, lang)
    parts = [t("explain_header", lang, screening=s["name"]), s["explain"]]
    if result_summary:
        # result_summary is staff-entered text already approved for patients.
        parts.append(result_summary)
    steps = "\n".join(f"• {step}" for step in s["next_steps"])
    parts += [t("next_steps_header", lang) + "\n" + steps, t("warning", lang, warning=s["warning"]), t("not_diagnosis", lang)]
    return "\n\n".join(parts)


def knowledge_for_llm(screening_type: str, lang: str, result_summary: str) -> str:
    """Everything the LLM may draw on for one case, and nothing else."""
    s = screening(screening_type, lang)
    clinic = CLINIC[lang if lang in LANGS else "en"]
    return "\n".join(
        [
            f"Screening: {s['name']}",
            f"Approved explanation: {s['explain']}",
            f"Case note approved for the patient: {result_summary or '(none)'}",
            "Approved next steps: " + " | ".join(s["next_steps"]),
            f"What to bring: {s['bring']}",
            f"Emergency warning signs: {s['warning']}",
            f"Clinic: {clinic['name']}, {clinic['address']}",
            "General: screening results are not a diagnosis; a clinician confirms. "
            "The follow-up visit is usually short. The patient can ask for a human at any time.",
        ]
    )
