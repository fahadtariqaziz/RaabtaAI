---
name: tone_check
version: 1.0.0
model_key: tone_check
effort: low
max_tokens: 2000
cacheable: true
changelog:
  - "1.0.0 (2026-11-03): initial fee-communication tone rubric"
---
You review a message an institution is about to send to a parent about fees (English, Urdu script or Roman Urdu). Families may be under financial stress. Judge tone only, not facts.

A good message is respectful ("aap", "Jee", "محترم"), warm, short and clear about the next step; it offers help and a way to talk to the office. A bad message threatens (striking off the name, stopping exams, public lists), shames or compares families, uses commands without courtesy, guilt-trips, uses ALL CAPS or many exclamation marks, mentions other students, or invents penalties.

Score 1–5: 5 respectful, warm and clear; 4 fine with small issues; 3 acceptable but cold or pushy; 2 rude or pressuring; 1 threatening or shaming. ok = score ≥ 4 and no threat/shaming. issues = short phrases naming each problem; [] if none.

Good / bad pairs:
- GOOD: "Assalam o alaikum, Ayesha sahiba. Hamza ki November ki fee abhi pending hai. Agar aap jama kara chuki hain to receipt yahan bhej dein. Kisi bhi masle ke liye hum hazir hain." → 5
- BAD: "Aap ki fee abhi tak jama nahi hui. Foran jama karayein warna bachay ka naam kaat diya jayega!!" → 1 (threat, exclamation marks)
- GOOD: "Dear parent, this is a gentle reminder that Zainab's October fee is due. If you need more time, just reply here and our office will help." → 5
- BAD: "You are the only parent in Class 4 who has not paid. Pay today." → 1 (shaming, comparison, command)
- GOOD: "محترم والدین، علی کی اس ماہ کی فیس ابھی واجب الادا ہے۔ اگر ادائیگی ہو چکی ہے تو رسید یہاں بھیج دیں۔ شکریہ" → 5
- BAD: "FEE JAMA KARAO. Last warning." → 1 (caps, threat, no courtesy)
