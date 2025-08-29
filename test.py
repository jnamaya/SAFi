from values import list_profiles, get_profile

# Should now return ['catholic', 'secular']
print("Available profiles:", list_profiles())

# Grab the secular profile
secular = get_profile("secular")
print("Secular profile name:", secular["name"])
print("Secular values:", [v["value"] for v in secular["values"]])