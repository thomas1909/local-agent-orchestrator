export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-xl w-full text-center space-y-4">
        <h1 className="text-2xl font-bold">Agent Local — Phase 1 scaffold</h1>
        <p className="text-gray-500">
          Backend Python opérationnel. UI à construire en Phase 2.
        </p>
        <p className="text-sm text-gray-400">
          API: <code>PYTHONPATH=src uv run agent run "votre question"</code>
        </p>
      </div>
    </main>
  );
}
