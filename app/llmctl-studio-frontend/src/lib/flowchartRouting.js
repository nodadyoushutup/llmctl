function normalizeMatchedConnectorIds(value) {
  if (!Array.isArray(value)) {
    return []
  }
  const seen = new Set()
  const connectorIds = []
  for (const item of value) {
    const connectorId = String(item || '').trim()
    if (!connectorId || seen.has(connectorId)) {
      continue
    }
    seen.add(connectorId)
    connectorIds.push(connectorId)
  }
  return connectorIds
}

export function routeCountMeta(routingState) {
  if (!routingState || typeof routingState !== 'object') {
    return null
  }
  const matchedConnectorIds = normalizeMatchedConnectorIds(routingState.matched_connector_ids)
  if (matchedConnectorIds.length > 0) {
    return { routeCount: matchedConnectorIds.length, reason: 'matched' }
  }
  const routeKey = String(routingState.route_key || '').trim()
  if (routeKey) {
    return { routeCount: 1, reason: 'route_key' }
  }
  if (routingState.no_match === true) {
    return { routeCount: 0, reason: 'no_match' }
  }
  return null
}
