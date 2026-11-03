# Demo — school-roman_ur (abc-grammar-school, whatsapp, roman_ur)

Clock frozen at 2026-11-03T05:00:00+00:00 · total cost $0.0763

**User:** Assalam o alaikum

**Assistant:** Walaikum assalam! ABC Grammar School mein aap ka khair maqdam hai. Aap ki kya madad kar sakta hoon? Admission, fee, classes, transport ya campus visit ke baare mein poochh sakte hain.

<sub>route: general/greeting/simple · tools: — · check: pass · kind: answer · sources: — · cost: $0.0005</sub>

**User:** Beta Class 3 mein admission lega, monthly fee kitni hai?

**Assistant:** Class 3 ki monthly tuition fee *PKR 12,500* hai.

Iske alawa ye one-time aur annual charges bhi hain:
- Admission fee: PKR 25,000 (one-time, non-refundable, admission confirm hone par)
- Security deposit: PKR 20,000 (one-time, refundable, school chhodne par clearance certificate ke saath)
- Annual charges: PKR 12,000 (April mein, lab, library aur activities ke liye)

Pehli payment ka exact total accounts office confirm karega.

Kya aap campus visit book karna chahenge? Main slot set kar deta hoon.

Source: ABC Grammar School — Fee structure, p. 1

<sub>route: admissions/fee_structure/simple · tools: get_fee_table · check: pass · kind: answer · sources: ABC Grammar School — Fee structure, p. 1 · cost: $0.0010</sub>

**User:** DHA se van ki facility hai? Kiraya kitna hai?

**Assistant:** DHA ke liye van route maujood hai. Is route mein DHA Phase 1–6 aur Cantt ke ilaqe shamil hain, aur monthly kiraya *PKR 8,500* hai.

Aap ka ilaqa is route mein aata hai ya nahi, ye office confirm kar sakta hai. Kya aap campus visit ka slot book karna chahenge? Main abhi set kar deta hoon.

Source: ABC Grammar School — Fee structure, p. 2

<sub>route: admissions/transport,fee_structure/simple · tools: get_transport_routes · check: pass · kind: answer · sources: ABC Grammar School — Fee structure, p. 2 · cost: $0.0008</sub>

**User:** Theek hai, is hafte campus visit karna hai

**Assistant:** Is baare mein abhi confirm maloomat mere paas nahi hai — office se confirm karke aap ko batate hain.

<sub>route: admissions/visit/complex · tools: get_visit_slots, get_visit_slots · check: fail · kind: fallback · sources: — · cost: $0.0740</sub>

