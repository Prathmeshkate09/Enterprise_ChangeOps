export default function Loading() {
  return (
    <main className="loading-shell" aria-busy="true" aria-label="Loading Control Tower">
      <div className="loading-brand" />
      <div className="loading-bar" />
      <div className="loading-grid">
        {Array.from({ length: 8 }, (_, index) => <div className="loading-card" key={index} />)}
      </div>
    </main>
  );
}
