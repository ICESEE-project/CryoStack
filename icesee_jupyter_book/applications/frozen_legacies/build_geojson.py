def build_flight_lines(
    rows,
    max_segment_jump_km: float = 120.0,
):
    import math

    def haversine_km(
        lon1,
        lat1,
        lon2,
        lat2,
    ):
        radius_km = 6371.0088

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)

        dphi = math.radians(
            lat2 - lat1
        )

        dlambda = math.radians(
            lon2 - lon1
        )

        a = (
            math.sin(dphi / 2.0) ** 2
            +
            math.cos(phi1)
            * math.cos(phi2)
            * math.sin(dlambda / 2.0) ** 2
        )

        c = 2.0 * math.atan2(
            math.sqrt(a),
            math.sqrt(1.0 - a),
        )

        return radius_km * c


    flights = {}

    for row in rows:
        flight = str(
            row.get("flight")
        )

        flights.setdefault(
            flight,
            [],
        ).append(row)


    features = []


    for (
        flight,
        records
    ) in sorted(
        flights.items()
    ):

        records = sorted(
            records,
            key=lambda r: (
                r.get("frame_idx")
                if r.get("frame_idx") is not None
                else 0
            ),
        )


        valid_records = [
            record
            for record in records
            if (
                record.get("lat") is not None
                and record.get("lon") is not None
            )
        ]


        if len(valid_records) < 2:
            continue


        segments = []
        current_segment = []


        previous = None


        for record in valid_records:

            lon = float(
                record["lon"]
            )

            lat = float(
                record["lat"]
            )


            if previous is None:

                current_segment = [
                    [lon, lat]
                ]

                previous = (
                    lon,
                    lat,
                )

                continue


            distance_km = haversine_km(
                previous[0],
                previous[1],
                lon,
                lat,
            )


            if (
                distance_km >
                max_segment_jump_km
            ):

                if (
                    len(current_segment) >= 2
                ):
                    segments.append(
                        current_segment
                    )


                current_segment = [
                    [lon, lat]
                ]

            else:

                current_segment.append(
                    [lon, lat]
                )


            previous = (
                lon,
                lat,
            )


        if (
            len(current_segment) >= 2
        ):
            segments.append(
                current_segment
            )


        if not segments:
            continue


        features.append(
            {
                "type": "Feature",

                "id": flight,

                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": segments,
                },

                "properties": {
                    "flight": flight,

                    "observations":
                        len(valid_records),

                    "segments":
                        len(segments),

                    "source":
                        valid_records[0].get(
                            "_source_file"
                        ),
                },
            }
        )


        print(
            f"[FrozenLegacies] "
            f"Flight {flight}: "
            f"{len(valid_records)} points, "
            f"{len(segments)} segments"
        )


    return {
        "type": "FeatureCollection",
        "features": features,
    }