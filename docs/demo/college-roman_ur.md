# Demo — college-roman_ur (punjab-model-college, whatsapp, roman_ur)

Clock frozen at 2026-11-03T05:00:00+00:00 · total cost $0.0322

**User:** AoA, FSc Pre-Medical ke liye kitne marks chahiye?

**Assistant:** Walaikum Assalam! 🙂

FSc Pre-Medical ke liye eligibility yeh hai: Matric (Science) mein kam az kam 70% marks.

Pehli merit list 5 September 2027 ko publish hogi.

Kya main aap ke liye counselling session book kar doon? Is se aap group ke baare mein bhi office se baat kar sakte hain.

Source: Punjab Model College — Prospectus 2027–29

<sub>route: admissions/eligibility/simple · tools: get_programs, get_key_dates · check: pass · kind: answer · sources: Punjab Model College — Prospectus 2027–29 · cost: $0.0008</sub>

**User:** Mere 91% marks hain, scholarship milegi?

**Assistant:** Is baare mein abhi confirm maloomat mere paas nahi hai — office se confirm karke aap ko batate hain.

<sub>route: admissions/scholarship,eligibility/simple · tools: get_scholarships · check: fail · kind: fallback · sources: — · cost: $0.0019</sub>

**User:** Fee kitni hai monthly?

**Assistant:** Jee, FSc Pre-Medical ki monthly tuition fee PKR 11,000 hai.

Counselling session ke liye bhi office se baat ho sakti hai. Kya main aap ke liye booking kar doon?

Source: Punjab Model College — Fee structure, p. 1

<sub>route: admissions/fee_structure/simple · tools: get_fee_table · check: pass · kind: answer · sources: Punjab Model College — Fee structure, p. 1 · cost: $0.0013</sub>

**User:** Counselling session book karna hai

**Assistant:** Jee zaroor! Counselling session ke liye yeh slots khaali hain:

- Monday 9 Nov, 11:00 AM
- Monday 9 Nov, 12:00 PM
- Tuesday 10 Nov, 11:00 AM

Session admin block ke counselling room mein hoga. Aap ko kaunsa waqt theek lagta hai?

<sub>route: admissions/counselling/complex · tools: get_visit_slots · check: pass · kind: answer · sources: — · cost: $0.0283</sub>

