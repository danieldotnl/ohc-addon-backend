# Our Home Connected | Versioning: Home Assistant Automations & Scripts Repository

## Important Notice

⚠️ **This repository is automatically maintained by the Our Home Connected | Versioning addon for Home Assistant. Manual edits to this repository are not recommended and may be overwritten during the next sync.**

The proper way to modify the files in this repository is through the Home Assistant UI or other standard Home Assistant configuration methods. Any changes made there will be automatically synced to this repository by the addon.

## Purpose of this Repository

This repository serves as a central storage location for all your Home Assistant automation and script configurations. It provides version control for your Home Assistant automations and scripts, allowing you to track changes, revert to previous versions, and keep a history of your home automation evolution. Each time a change is made to your automations or scripts in Home Assistant, the OHC addon automatically commits those changes to this repository, creating a comprehensive history of your smart home configuration.

### Benefits:

- **Version History**: Track all changes made to your automations and scripts
- **Backup Protection**: Never lose your complex automation configurations again
- **Change Rollback**: Easily revert to previous versions if something breaks
- **Configuration Sharing**: Share your configurations with others more easily

## Sharing Your Automations

We encourage you to consider making this repository public to help the Home Assistant community learn from your automations and scripts.

**Important security considerations if sharing publicly:**

- Make sure your automations don't contain sensitive information like API keys, passwords, or personal data
- Use Home Assistant's `secrets.yaml` file for any sensitive values
- Review your automations for location data or other personal information before sharing
- Consider obscuring specific device names or identifiers that could reveal too much about your home setup

If you accidentally commit sensitive information, don't panic. GitHub provides [several ways to remove sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) from a repository.

Sharing your automations can be incredibly valuable to the community, but always prioritize your privacy and security.

## Repository Structure

- `/automations/` - Contains all your Home Assistant automations in YAML format
- `/scripts/` - Contains all your scripts in YAML format
- `/.ohcstate/` - Contains state information used by the OHC addon (do not modify)

## Get Our Home Connected | Versioning for Your Home Assistant

If you've discovered this repository and don't have the Our Home Connected | Versioning addon installed yet, you're missing out!

The Our Home Connected | Versioning addon for Home Assistant provides:

- Automatic version control for your automations and scripts (what created this repository)
- [Future features coming soon!]

### Installation Instructions:

1. Add our repository to your Home Assistant Add-on Store:
   ```
   https://github.com/ourHomeConnected/ha-addons
   ```
2. Install the "Our Home Connected | Versioning" addon
3. Configure with your GitHub credentials
4. Start enjoying automated version control!

## Support & Community

- GitHub: [https://github.com/ourHomeConnected](https://github.com/ourHomeConnected)
- Documentation: [Link to documentation]

---

_This repository is powered by Our Home Connected - Making home automation more connected, more powerful, more yours._
