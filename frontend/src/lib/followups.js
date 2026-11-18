// Contextual follow-up suggestions — logic unchanged from the original frontend.
export function getFollowUpQuestions(question = "", answer = "") {
  const text = `${question} ${answer}`.toLowerCase();
  if (/admission|eapcet|ecet|management quota|seat distribution|eligib/.test(text)) return [
    "What are the eligibility criteria for B.Tech admission?",
    "How does the management quota admission process work?",
    "What documents are required during admission?",
  ];
  if (/placement|package|recruit|company|placed|career/.test(text)) return [
    "Which companies recruited SVCE students?",
    "Can you show placement statistics for other departments?",
    "What is the highest package reported by each department?",
  ];
  if (/department|course|branch|program|b\.tech|engineering/.test(text)) return [
    "What specializations are available in B.Tech?",
    "What is the admission process for these departments?",
    "What placement opportunities are available for each branch?",
  ];
  if (/fee|tuition|scholarship|payment|cost/.test(text)) return [
    "Are scholarships or fee reimbursements available?",
    "What other fees should students expect?",
    "How can I confirm the current official fee structure?",
  ];
  if (/contact|phone|email|address|location|reach/.test(text)) return [
    "What is the college's full address?",
    "How can I contact the admissions office?",
    "Where can I find the official SVCE website?",
  ];
  return [
    "Can you explain this in more detail?",
    "Where can I find the official information about this?",
    "What related information should I know?",
  ];
}
