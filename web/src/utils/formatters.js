export function formatTimestamp(timestamp) {
  if (timestamp === null || timestamp === undefined) return 'Unknown';

  try {
    let parsedDate;
    if (typeof timestamp === 'string') {
      parsedDate = new Date(timestamp);
      if (Number.isNaN(parsedDate.getTime())) {
        const numeric = Number(timestamp);
        parsedDate = new Date(numeric);
      }
    } else {
      parsedDate = new Date(Number(timestamp));
    }

    if (Number.isNaN(parsedDate.getTime())) {
      return 'Unknown';
    }

    return parsedDate.toLocaleString();
  } catch {
    return 'Unknown';
  }
}

export function formatDuration(start, end) {
  if (!start || !end) return null;

  const startMs = Number(start);
  const endMs = Number(end);

  if (Number.isNaN(startMs) || Number.isNaN(endMs)) {
    return null;
  }

  const totalSeconds = Math.max(0, Math.round((endMs - startMs) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  if (minutes === 0) {
    return `${seconds}s`;
  }

  return `${minutes}m ${seconds.toString().padStart(2, '0')}s`;
}

export function formatStatusLabel(status) {
  if (!status) {
    return 'Pending';
  }

  return status
    .toString()
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

