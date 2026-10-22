from sqlmodel import Session, select
from app.database.models import Doctor, Service, ClinicConfig
from app.database.session import engine
from app.config import settings


def seed_database():
    with Session(engine) as session:
        # Check if already seeded
        existing_doc = session.exec(select(Doctor)).first()
        if existing_doc:
            return

        doctors = [
            Doctor(
                name="د. علي الفرجاني",
                specialty="عظام ومفاصل",
                room_number="عيادة 101 (الدور الأول)",
                regular_schedule="السبت، الإثنين، الأربعاء (4:00 م - 8:00 م)",
                schedule_days="السبت,الإثنين,الأربعاء",
                today_status="available",
                today_note="",
                consultation_fee=50.0,
            ),
            Doctor(
                name="د. فاطمة الورفلي",
                specialty="أطفال وحديثي ولادة",
                room_number="عيادة 104 (الدور الأول)",
                regular_schedule="يومياً عدا الجمعة (4:00 م - 7:30 م)",
                schedule_days="السبت,الأحد,الإثنين,الثلاثاء,الأربعاء,الخميس",
                today_status="available",
                today_note="",
                consultation_fee=40.0,
            ),
            Doctor(
                name="د. محمد الترهوني",
                specialty="باطنة وجهاز هضمي",
                room_number="عيادة 102 (الدور الأول)",
                regular_schedule="الأحد، الثلاثاء، الخميس (10:00 ص - 2:00 م)",
                schedule_days="الأحد,الثلاثاء,الخميس",
                today_status="available",
                today_note="",
                consultation_fee=45.0,
            ),
            Doctor(
                name="د. مروان القماطي",
                specialty="عيون وجراحة الشبكية",
                room_number="عيادة 201 (الدور الثاني)",
                regular_schedule="السبت، الثلاثاء (5:00 م - 8:30 م)",
                schedule_days="السبت,الثلاثاء",
                today_status="available",
                today_note="",
                consultation_fee=40.0,
            ),
            Doctor(
                name="د. سارة بن نصر",
                specialty="نساء وتوليد",
                room_number="عيادة 105 (الدور الأول)",
                regular_schedule="السبت، الإثنين، الخميس (11:00 ص - 3:00 م)",
                schedule_days="السبت,الإثنين,الخميس",
                today_status="available",
                today_note="",
                consultation_fee=50.0,
            ),
            Doctor(
                name="د. خالد الزنتاني",
                specialty="أنف وأذن وحنجرة",
                room_number="عيادة 103 (الدور الأول)",
                regular_schedule="الأحد، الثلاثاء، الأربعاء (5:00 م - 8:00 م)",
                schedule_days="الأحد,الثلاثاء,الأربعاء",
                today_status="available",
                today_note="",
                consultation_fee=40.0,
            ),
        ]

        services = [
            Service(
                category="مختبر",
                name="تحليل سكر دم صائم (FBS)",
                price=15.0,
                prep_instructions="يشترط الصيام التام عن الأكل والشرب عدا الماء العادي لمدة 8 إلى 10 ساعات قبل إجراء التحليل.",
                availability="المختبر يعمل على مدار 24 ساعة",
            ),
            Service(
                category="مختبر",
                name="تحليل السكر التراكمي (HbA1c)",
                price=30.0,
                prep_instructions="لا يتطلب الصيام إطلاقاً، يمكن إجراؤه في أي وقت من اليوم.",
                availability="المختبر يعمل 24 ساعة",
            ),
            Service(
                category="مختبر",
                name="تحليل صورة الدم الكاملة (CBC)",
                price=25.0,
                prep_instructions="لا يتطلب صيام مسبق.",
                availability="المختبر يعمل 24 ساعة",
            ),
            Service(
                category="مختبر",
                name="تحليل وظائف كلى (اليوريا والكرياتينين)",
                price=30.0,
                prep_instructions="يفضل الصيام الخفيف من 6 إلى 8 ساعات، مع شرب الماء العادي.",
                availability="المختبر يعمل 24 ساعة",
            ),
            Service(
                category="مختبر",
                name="تحليل دهون كاملة / كوليسترول (Lipid Profile)",
                price=35.0,
                prep_instructions="يشترط الصيام لمدة تتراوح بين 10 إلى 12 ساعة (يُسمح بشرب الماء فقط).",
                availability="المختبر يعمل 24 ساعة",
            ),
            Service(
                category="أشعة",
                name="تصوير تلفزيوني سونار بطن وحوض (Ultrasound)",
                price=60.0,
                prep_instructions="صيام 6 ساعات عن الطعام، وشرب لتر ماء قبل موعد الفحص بساعة واحدة مع حبس البول لتكون المثانة ممتلئة.",
                availability="قسم الأشعة من 8:00 صباحاً حتى 10:00 مساءً",
            ),
            Service(
                category="أشعة",
                name="أشعة سينية ديجيتال (X-Ray)",
                price=35.0,
                prep_instructions="لا توجد شروط خاصة، يرجى إزالة أي إكسسوارات أو معادن من منطقة التصوير.",
                availability="طوارئ الأشعة متاح 24 ساعة",
            ),
            Service(
                category="طوارئ",
                name="تخطيط قلب كهربائي (ECG)",
                price=25.0,
                prep_instructions="فحص فوري بدون شروط مسبقة.",
                availability="قسم الإسعاف والطوارئ يعمل 24 ساعة",
            ),
        ]

        configs = [
            ClinicConfig(key="clinic_name", value=settings.CLINIC_NAME, description="اسم المصحة"),
            ClinicConfig(key="address", value=settings.CLINIC_ADDRESS, description="العنوان التفصيلي"),
            ClinicConfig(key="map_link", value=settings.CLINIC_MAP_LINK, description="رابط الموقع على الخريطة"),
            ClinicConfig(key="emergency_phone", value=settings.EMERGENCY_PHONE, description="أرقام الإسعاف والطوارئ"),
            ClinicConfig(key="reception_phone", value=settings.RECEPTION_PHONE, description="هاتف الاستعلامات"),
            ClinicConfig(key="booking_policy", value=settings.BOOKING_POLICY, description="سياسة ونظام الحجز"),
            ClinicConfig(key="working_hours", value="قسم الطوارئ والمختبر والأشعة: 24 ساعة يومياً. العيادات التخصصية: من 8:00 صباحاً إلى 10:00 مساءً.", description="ساعات العمل"),
            ClinicConfig(key="authorized_phones", value="0912345678,0921111111,218912345678,0945361562", description="أرقام الموظفين المصرح لهم بالتعديل في الخاص"),
        ]

        session.add_all(doctors)
        session.add_all(services)
        session.add_all(configs)
        session.commit()
