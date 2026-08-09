TAG_MAPPING = {
    "Common": "Splash & Languages",
    "common": "Splash & Languages",
    "Auth": "Auth & Security",
    "auth": "Auth & Security",
    "Users": "Users & Profiles",
    "users": "Users & Profiles",
    "Emergency SOS": "Users & Profiles",
    "emergency-sos": "Users & Profiles",
    "Learning": "Home & Learning",
    "learning": "Home & Learning",
    "Midwives": "Midwives & Consult Hub",
    "midwives": "Midwives & Consult Hub",
    "Appointments": "Appointments",
    "appointments": "Appointments",
    "Consultations": "Consultations",
    "consultations": "Consultations",
    "Chat": "Real-Time Chat",
    "chat": "Real-Time Chat",
    "AI Assistant": "AI Assistant",
    "ai-assistant": "AI Assistant",
    "ai_assistant": "AI Assistant",
    "Notifications": "Notifications",
    "notifications": "Notifications",
    "Reviews": "Reviews & Ratings",
    "reviews": "Reviews & Ratings",
}

ORDERED_TAG_NAMES = [
    "Splash & Languages",
    "Auth & Security",
    "Users & Profiles",
    "Home & Learning",
    "Midwives & Consult Hub",
    "Appointments",
    "Consultations",
    "Real-Time Chat",
    "AI Assistant",
    "Notifications",
    "Reviews & Ratings",
]


def cagh_openapi_tag_postprocessor(result, generator, **kwargs):
    """
    DRF Spectacular Postprocessing Hook:
    Reorders and renames OpenAPI tags to present a clean, organized Swagger UI.
    """
    paths = result.get("paths", {})
    for path, methods in paths.items():
        for method, operation in methods.items():
            if isinstance(operation, dict) and "tags" in operation:
                new_tags = []
                for t in operation.get("tags", []):
                    mapped = TAG_MAPPING.get(t, t)
                    if mapped not in new_tags:
                        new_tags.append(mapped)
                operation["tags"] = new_tags

    # Set ordered tag list
    existing_tags = result.get("tags", [])
    tag_desc_map = {t["name"]: t.get("description", "") for t in existing_tags if isinstance(t, dict)}

    new_tags_list = []
    for name in ORDERED_TAG_NAMES:
        new_tags_list.append({
            "name": name,
            "description": tag_desc_map.get(name, "")
        })

    # Include any unmapped tags at the end
    for t in existing_tags:
        if isinstance(t, dict) and t["name"] not in ORDERED_TAG_NAMES:
            new_tags_list.append(t)

    result["tags"] = new_tags_list
    return result
