function StatusBadge({ status, label, className = '' }) {
  const statusMap = {
    active: { class: 'status-badge--active', defaultLabel: 'Active' },
    offline: { class: 'status-badge--offline', defaultLabel: 'Offline' },
    pending: { class: 'status-badge--pending', defaultLabel: 'Pending' },
    processing: { class: 'status-badge--processing', defaultLabel: 'Processing' },
    completed: { class: 'status-badge--completed', defaultLabel: 'Completed' },
    error: { class: 'status-badge--error', defaultLabel: 'Error' },
    blocked: { class: 'status-badge--blocked', defaultLabel: 'Blocked' },
  };

  const statusConfig = statusMap[status?.toLowerCase()] || statusMap.pending;
  const displayLabel = label || statusConfig.defaultLabel;

  return (
    <span className={`status-badge ${statusConfig.class} ${className}`}>
      {displayLabel}
    </span>
  );
}

export default StatusBadge;


