// SPDX-License-Identifier: MIT
pragma solidity 0.8.17;

import {ERC721AUpgradeable, IERC721AUpgradeable} from "erc721a-upgradeable/contracts/ERC721AUpgradeable.sol";
import {ERC721AQueryableUpgradeable} from "erc721a-upgradeable/contracts/extensions/ERC721AQueryableUpgradeable.sol";
import {DefaultOperatorFiltererUpgradeable} from
    "operator-filter-registry/src/upgradeable/DefaultOperatorFiltererUpgradeable.sol";
import {AccessControlEnumerableUpgradeable} from
    "@openzeppelin/contracts-upgradeable/access/AccessControlEnumerableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {MerkleProofUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/cryptography/MerkleProofUpgradeable.sol";
import {ERC2981Upgradeable} from "@openzeppelin/contracts-upgradeable/token/common/ERC2981Upgradeable.sol";

import {IAppliedPrimateEngineeringModified} from "./interfaces/IAppliedPrimateEngineeringModified.sol";
import {IAllegiancePass} from "./interfaces/IAllegiancePass.sol";

/**
 * @title MegaForceSentinels
 * @author fragment.xyz
 */
contract MegaForceSentinels is
    UUPSUpgradeable,
    ERC721AUpgradeable,
    AccessControlEnumerableUpgradeable,
    ERC721AQueryableUpgradeable,
    DefaultOperatorFiltererUpgradeable,
    ERC2981Upgradeable
{
    error MaxTotalSupplyError();
    error InsufficientFundsError();
    error TransferFailedError();
    error CannotBeNullError();
    error PhaseNotActiveError();
    error MaxDevMintPerTx();
    error MaxMintPerTx();

    uint256 public constant MAX_TOTAL_SUPPLY = 10000;
    bytes32 public constant OPEN = keccak256("OPEN");
    bytes32 public constant OPERATOR_ROLE = keccak256(bytes("OPERATOR"));

    bytes32[] NON_KEYCARD_TRAITS;

    string private _baseTokenURI;
    IAppliedPrimateEngineeringModified public keyCard;
    IAllegiancePass public mintPass;
    bytes32 public root;
    address public signer;
    bool public phaseOneActive;
    bool public phaseTwoActive;

    mapping(bytes32 => KeycardLimits) public keycardLimits;
    mapping(uint256 => bool) public redeemedKeycards;
    mapping(address => uint256) public publicMintedTokens;
    mapping(address => uint256) public phaseTwoMintedTokens;
    uint256 public softCap;

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /**
     * @dev Initializes the Sentinel Token contract.
     * @param _keyCard The address of the Primate Keycard.
     * @param _pass The address of the Allegaince Pass contract.
     * @param _root The Merkle root phase two of mint.
     * @param _signer The address avtivated wallet signer.
     * @param _owner The address of the contract owner.
     */
    function initialize(address _keyCard, address _pass, bytes32 _root, address _signer, address _owner)
        public
        initializerERC721A
        initializer
    {
        __ERC721A_init("MegaForce Sentinels", "SENTINEL");
        __ERC721AQueryable_init();
        __DefaultOperatorFilterer_init();
        __UUPSUpgradeable_init();

        _setupRole(DEFAULT_ADMIN_ROLE, _owner);
        _setupRole(OPERATOR_ROLE, _msgSender());

        keyCard = IAppliedPrimateEngineeringModified(_keyCard);
        mintPass = IAllegiancePass(_pass);
        root = _root;
        signer = _signer;
        //set starting limits
        keycardLimits[keccak256("FULL_GOLD")] = KeycardLimits(8, 4, 4, 2, 0.08 ether);
        keycardLimits[keccak256("GOLD")] = KeycardLimits(6, 2, 4, 1, 0.157 ether);
        keycardLimits[keccak256("FULL_SILVER")] = KeycardLimits(5, 1, 4, 0, 0.157 ether);
        keycardLimits[keccak256("SILVER")] = KeycardLimits(3, 1, 2, 0, 0.157 ether);
        keycardLimits[keccak256("NOKEYCARD")] = KeycardLimits(2, 0, 0, 0, 0.169 ether);
        keycardLimits[keccak256("PHASETWO")] = KeycardLimits(2, 0, 0, 0, 0.2 ether);
        NON_KEYCARD_TRAITS = [
            keccak256("TRIPPY"),
            keccak256("JELLY"),
            keccak256("DEMON"),
            keccak256("FIRE"),
            keccak256("RUNES"),
            keccak256("DMT"),
            keccak256("CRYSTALS"),
            keccak256("ICE"),
            keccak256("SAND"),
            keccak256("MARINE")
        ];
    }

    event MintedToken(uint256 indexed tokenId, bytes32 indexed trait);
    event BatchMetadataUpdate(uint256 _fromTokenId, uint256 _toTokenId);

    struct MintData {
        uint256 keyCardTokenId;
        uint256 mintPassTokenId;
        uint256 numTokens;
        bytes32[] keycardTraitsToMint;
        bytes32[] nonKeycardTraitsToMint;
        uint256 currentTokenId;
    }

    struct KeycardLimits {
        uint8 maxTokens;
        uint8 maxKeyCardTraits;
        uint8 maxNonKeycardTraits;
        uint8 freeTokens;
        uint128 costPerToken;
    }

    function setSoftCap(uint256 _softCap) external onlyRole(OPERATOR_ROLE) {
        softCap = _softCap;
    }

    /**
     * @dev Check token existence.
     * @param tokenId The ID of the token to check.
     */
    function exists(uint256 tokenId) public view returns (bool) {
        return _exists(tokenId);
    }

    /**
     * @dev Allows public minting of tokens during Phase Two.
     * @notice This function impilemts the @openzeppelin Merkle tree impilentation
     * @param numTokens The number of tokens to mint.
     */
    function publicMint(uint256 numTokens) external payable {
        if (!phaseTwoActive) revert PhaseNotActiveError();

        uint256 currentTokenId = totalSupply();
        if (_totalMinted() + numTokens > softCap) {
            revert MaxTotalSupplyError();
        }

        KeycardLimits memory keycardLimit = keycardLimits[keccak256("PHASETWO")];

        if (numTokens > 100) revert MaxMintPerTx();

        if (numTokens * keycardLimit.costPerToken != msg.value) revert InsufficientFundsError();

        for (uint8 i; i < numTokens; i++) {
            emit MintedToken(currentTokenId, OPEN);
            currentTokenId++;
        }
        _mint(_msgSender(), numTokens);
    }

    /**
     * @dev Withdraws Ether from the contract to the owner.
     */
    function withdrawEther(uint256 amount) external onlyRole(OPERATOR_ROLE) {
        if (amount == 0) amount = address(this).balance;

        if (amount > address(this).balance) revert InsufficientFundsError();
        (bool success,) = owner().call{value: amount}("");
        if (!success) revert TransferFailedError();
    }

    /**
     * @dev Mints tokens for the team.
     * @param numTokens The number of tokens to mint.
     * @param to The address to mint the tokens to.
     * @param traits The traits to be associated with the minted tokens.
     */
    function devMint(uint256 numTokens, address to, bytes32[] memory traits) external onlyRole(OPERATOR_ROLE) {
        if (numTokens > 250) revert MaxDevMintPerTx();
        uint256 currentTokenId = totalSupply();
        for (uint8 i; i < numTokens; i++) {
            if (traits.length > i) {
                emit MintedToken(currentTokenId, traits[i]);
                currentTokenId++;
            } else {
                emit MintedToken(currentTokenId, OPEN);
                currentTokenId++;
            }
        }
        _mint(to, numTokens);
    }

    /**
     * @dev Sets the state of phase one mint .
     * @param state The new state of Phase one.
     */
    function setPhaseOneState(bool state) external onlyRole(OPERATOR_ROLE) {
        phaseOneActive = state;
    }

    /**
     * @dev Sets the state of phase two mint .
     * @param state The new state of Phase two.
     */
    function setPhaseTwoState(bool state) external onlyRole(OPERATOR_ROLE) {
        phaseTwoActive = state;
    }

    /**
     * @dev Sets the limits for a specific keycard type.
     * @param key The bytes32 key representing the keycard type.
     * @param _maxTokens The maximum tokens that can be minted.
     * @param _maxKeyCardTraits The maximum keycard traits allowed.
     * @param _maxNoneKeycardTraitsTraits The maximum non keycard traits allowed.
     * @param _freeTokens The number of free tokens associated with the keycard type.
     * @param _costPerToken The cost per token for the keycard
     */
    function setKeycardLimits(
        bytes32 key,
        uint8 _maxTokens,
        uint8 _maxKeyCardTraits,
        uint8 _maxNoneKeycardTraitsTraits,
        uint8 _freeTokens,
        uint128 _costPerToken
    ) external onlyRole(OPERATOR_ROLE) {
        keycardLimits[key] = KeycardLimits({
            maxTokens: _maxTokens,
            maxKeyCardTraits: _maxKeyCardTraits,
            maxNonKeycardTraits: _maxNoneKeycardTraitsTraits,
            freeTokens: _freeTokens,
            costPerToken: _costPerToken
        });
    }

    /**
     * @dev Returns the contract owner address.
     * @return owner address.
     */
    function owner() public view virtual returns (address) {
        return getRoleMember(DEFAULT_ADMIN_ROLE, 0);
    }

    /**
     * @dev Adds an operator to the contract.
     * @param operator The address of the operator to be added.
     */
    function addOperator(address operator) public onlyRole(OPERATOR_ROLE) {
        if (operator == address(0)) revert CannotBeNullError();
        _grantRole(OPERATOR_ROLE, operator);
    }

    /**
     * @dev Returns the base URI for the contract.
     * @return base URI.
     */
    function _baseURI() internal view virtual override returns (string memory) {
        return _baseTokenURI;
    }

    /**
     * @dev Sets the base URI for the contract.
     * @param baseURI The base URI to be set.
     */
    function setBaseURI(string calldata baseURI) external onlyRole(OPERATOR_ROLE) {
        _baseTokenURI = baseURI;
        emit BatchMetadataUpdate(0, totalSupply());
    }

    /**
     * @dev Sets the royalty information for the contract.
     * @param receiver The address of the royalty receiver.
     * @param value The royalty value.
     */
    function setRoyaltyInfo(address receiver, uint96 value) public onlyRole(OPERATOR_ROLE) {
        _setDefaultRoyalty(receiver, value);
    }

    /**
     * @dev Authorizes an upgrade for the contract.
     * @param newImplementation The address of the new implementation to be authorized.
     */
    function _authorizeUpgrade(address newImplementation) internal override onlyRole(OPERATOR_ROLE) {}

    /**
     * @dev Checks if the contract supports a specific interface.
     * @param interfaceId The interface identifier to check for support.
     * @return boolean value indicating whether the contract supports the specified interface.
     */
    function supportsInterface(bytes4 interfaceId)
        public
        view
        virtual
        override(IERC721AUpgradeable, ERC721AUpgradeable, AccessControlEnumerableUpgradeable, ERC2981Upgradeable)
        returns (bool)
    {
        return interfaceId == type(IERC721AUpgradeable).interfaceId
            || AccessControlEnumerableUpgradeable.supportsInterface(interfaceId)
            || ERC721AUpgradeable.supportsInterface(interfaceId) || ERC2981Upgradeable.supportsInterface(interfaceId)
            || super.supportsInterface(interfaceId);
    }

    function setApprovalForAll(address operator, bool approved)
        public
        override(IERC721AUpgradeable, ERC721AUpgradeable)
        onlyAllowedOperatorApproval(operator)
    {
        super.setApprovalForAll(operator, approved);
    }

    function approve(address operator, uint256 tokenId)
        public
        payable
        override(IERC721AUpgradeable, ERC721AUpgradeable)
        onlyAllowedOperatorApproval(operator)
    {
        super.approve(operator, tokenId);
    }

    function transferFrom(address from, address to, uint256 tokenId)
        public
        payable
        override(IERC721AUpgradeable, ERC721AUpgradeable)
        onlyAllowedOperator(from)
    {
        super.transferFrom(from, to, tokenId);
    }

    function safeTransferFrom(address from, address to, uint256 tokenId)
        public
        payable
        override(IERC721AUpgradeable, ERC721AUpgradeable)
        onlyAllowedOperator(from)
    {
        super.safeTransferFrom(from, to, tokenId);
    }

    function safeTransferFrom(address from, address to, uint256 tokenId, bytes memory data)
        public
        payable
        override(IERC721AUpgradeable, ERC721AUpgradeable)
        onlyAllowedOperator(from)
    {
        super.safeTransferFrom(from, to, tokenId, data);
    }
}
