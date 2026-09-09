type Props = { compact?: boolean };

export function Brand({ compact = false }: Props) {
  return (
    <div className="brand-lockup" aria-label="PaperForge">
      <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
      <span className="brand-word">PaperForge</span>
      {!compact && <span className="brand-edition">Research workspace</span>}
    </div>
  );
}
