import { CircleMarker, MapContainer, Polyline, TileLayer } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet'
import type { Coordinates, Place } from '../types'
import { t, type Lang } from '../i18n'
import { formatKm } from '../lib/format'

interface Props {
  campus: Coordinates
  city: Place | null
  distanceKm: number | null
  lang: Lang
}

/** Full-bleed 420 px map (B5.11): desaturated OSM tiles, red campus dot, black city dot,
 *  1.5 px black line between them, caption with the distance. */
export default function MapSection({ campus, city, distanceKm, lang }: Props) {
  const campusPoint: LatLngExpression = [campus.lat, campus.lon]
  const cityPoint: LatLngExpression | null = city?.coords ? [city.coords.lat, city.coords.lon] : null
  const bounds: LatLngBoundsExpression | undefined = cityPoint ? [campusPoint, cityPoint] : undefined
  return (
    <section aria-label={t(lang, 'map_aria')} className="mt-10">
      <div className="map -mx-gutter">
        <MapContainer
          className="map"
          bounds={bounds}
          boundsOptions={{ padding: [48, 48] }}
          center={bounds ? undefined : campusPoint}
          zoom={bounds ? undefined : 14}
          scrollWheelZoom={false}
          zoomControl={false}
          attributionControl
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
          />
          {cityPoint && (
            <>
              <Polyline positions={[campusPoint, cityPoint]} pathOptions={{ color: '#000000', weight: 1.5 }} />
              <CircleMarker
                center={cityPoint}
                radius={7}
                pathOptions={{ color: '#000000', fillColor: '#000000', fillOpacity: 1, weight: 0 }}
              />
            </>
          )}
          <CircleMarker
            center={campusPoint}
            radius={8}
            pathOptions={{ color: '#e3271a', fillColor: '#e3271a', fillOpacity: 1, weight: 0 }}
          />
        </MapContainer>
      </div>
      <p className="mt-3 text-[13px] text-ink-2 max-w-[70ch]">
        {distanceKm != null
          ? t(lang, 'map_caption', { km: formatKm(distanceKm, lang) })
          : t(lang, 'map_caption', { km: '—' })}
      </p>
    </section>
  )
}
