export function JsonLd({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

export const organizationSchema = {
  "@context": "https://schema.org",
  "@type": "EducationalOrganization",
  name: "CPMAI Prep",
  url: "https://cpmaiexamprep.com",
  logo: "https://cpmaiexamprep.com/logo.png",
  sameAs: [
    "https://twitter.com/cpmaiprep",
    "https://www.linkedin.com/company/cpmai-prep",
  ],
};

export const courseSchema = {
  "@context": "https://schema.org",
  "@type": "Course",
  name: "CPMAI Certification Preparation",
  description:
    "Comprehensive preparation for the Cognitive Project Management for AI certification.",
  provider: {
    "@type": "Organization",
    name: "CPMAI Prep",
    sameAs: "https://cpmaiexamprep.com",
  },
  hasCourseInstance: {
    "@type": "CourseInstance",
    courseMode: "online",
    courseWorkload: "PT60H",
  },
};

export const faqSchema = (qs: { q: string; a: string }[]) => ({
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: qs.map(({ q, a }) => ({
    "@type": "Question",
    name: q,
    acceptedAnswer: { "@type": "Answer", text: a },
  })),
});
