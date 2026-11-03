# Demo — school-en (abc-grammar-school, widget, en)

Clock frozen at 2026-11-03T05:00:00+00:00 · total cost $0.0032

**User:** Hi, what is the admission fee and security deposit?

**Assistant:** Here are the one-time charges for 2026-27 (applicable to all classes):

- Admission fee: PKR 25,000 (one-time, non-refundable; payable on confirmation of admission)
- Security deposit: PKR 20,000 (one-time, refundable on leaving the school with a clearance certificate)

If you would like to see the campus before applying, I can book a visit for you. Would you like that?

<sub>route: admissions/fee_structure/simple · tools: get_fee_table · check: pass · kind: answer · sources: ABC Grammar School — Fee structure, p. 1 · cost: $0.0011</sub>

**User:** Is there a discount for a second child?

**Assistant:** Yes, the school offers a sibling discount for 2026-27:

- Second child: 10% tuition discount
- Third child: 15% tuition discount

The discount applies to tuition, so the accounts office can confirm the exact amount for your children's classes. Would you like me to book a campus visit so the office can go over this with you?

<sub>route: admissions/fee_structure,scholarship/simple · tools: get_scholarships · check: pass · kind: answer · sources: ABC Grammar School — Prospectus 2026–27 · cost: $0.0007</sub>

**User:** What documents do we need?

**Assistant:** Here are the documents required for admission at ABC Grammar School:

- B-Form of the child
- CNIC copies of both parents
- Last school's result card and School Leaving Certificate (for Class 1 and above)
- Four passport-size photographs

You can collect the admission form from the school office for a form fee of PKR 2,000, or book a campus visit where the office can guide you through the process. Would you like me to book a visit for you?

<sub>route: admissions/admission_process/simple · tools: search_knowledge · check: pass · kind: answer · sources: ABC Grammar School — Prospectus 2026–27, p. 1 · cost: $0.0015</sub>

