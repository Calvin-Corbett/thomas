const videos = [
  {
    id: "replace_me_1",
    title: "How Thomas started",
    summary: "The vision and early release direction.",
  },
  {
    id: "replace_me_2",
    title: "Behind the product updates",
    summary: "What changed and why it matters for users.",
  },
  {
    id: "replace_me_3",
    title: "Roadmap and future goals",
    summary: "Where Thomas is going next.",
  },
];

export default function JourneyPage() {
  return (
    <section className="section-shell">
      <p className="eyebrow">Thomas Journey</p>
      <h1 className="page-title">Follow the build in public.</h1>
      <p className="page-intro">
        Share your official YouTube updates here so users can follow product direction and trust the roadmap.
      </p>

      <div className="video-grid">
        {videos.map((video) => (
          <article key={video.id} className="video-card">
            <div className="video-shell">
              {video.id.startsWith("replace_me_") ? (
                <div className="video-placeholder">
                  Replace YouTube ID in <code>apps/site/src/app/journey/page.tsx</code>
                </div>
              ) : (
                <iframe
                  src={`https://www.youtube.com/embed/${video.id}`}
                  title={video.title}
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                  referrerPolicy="strict-origin-when-cross-origin"
                  allowFullScreen
                />
              )}
            </div>
            <h2>{video.title}</h2>
            <p>{video.summary}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
